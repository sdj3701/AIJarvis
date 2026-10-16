"""Persistent local vector DB and FTS5 conversation memory.

sqlite-vec executes exact cosine search in SQLite. Text, metadata, FTS rows and
float32 vectors share transactions. Model identities prevent cross-model search.
"""

from __future__ import annotations

import json
import sqlite3
import struct
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from app.config.models import SemanticSettings
from app.rag.chunker import chunk_text
from app.rag.embeddings import reciprocal_rank_fusion
from app.rag.local_embedder import (
    Embedder,
    LocalOllamaEmbedder,
    embed_document,
    embed_query,
    normalized_vector,
    retrieval_identity,
)
from app.rag.reranker import Candidate, Reranker


class EventSink(Protocol):
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS semantic_items (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, group_id TEXT NOT NULL,
    text TEXT NOT NULL, metadata TEXT NOT NULL,
    model TEXT, dim INTEGER, vector BLOB
);
CREATE INDEX IF NOT EXISTS semantic_group ON semantic_items(group_id);
CREATE INDEX IF NOT EXISTS semantic_model ON semantic_items(kind, model, dim);
CREATE VIRTUAL TABLE IF NOT EXISTS semantic_fts USING fts5(
    text, content='semantic_items', content_rowid='rowid', tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS semantic_ai AFTER INSERT ON semantic_items BEGIN
    INSERT INTO semantic_fts(rowid,text) VALUES(new.rowid,new.text);
END;
CREATE TRIGGER IF NOT EXISTS semantic_ad AFTER DELETE ON semantic_items BEGIN
    INSERT INTO semantic_fts(semantic_fts,rowid,text) VALUES('delete',old.rowid,old.text);
END;
CREATE TRIGGER IF NOT EXISTS semantic_au AFTER UPDATE OF text ON semantic_items BEGIN
    INSERT INTO semantic_fts(semantic_fts,rowid,text) VALUES('delete',old.rowid,old.text);
    INSERT INTO semantic_fts(rowid,text) VALUES(new.rowid,new.text);
END;
CREATE TABLE IF NOT EXISTS conversation_turns (
    turn_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, question TEXT NOT NULL,
    answer TEXT NOT NULL, created_at TEXT NOT NULL, metadata TEXT NOT NULL
);
PRAGMA user_version=1;
"""


def _fts_query(text: str) -> str:
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in text.split()) or '""'


class SemanticMemory:
    def __init__(
        self,
        path: Path,
        settings: SemanticSettings,
        *,
        embedder: Embedder | None = None,
        events: EventSink | None = None,
        rrf_k: int = 60,
        reranker: Reranker | None = None,
    ) -> None:
        self.path = path
        self.settings = settings
        self.embedder = embedder or LocalOllamaEmbedder(settings.model, settings.timeout_s)
        self.events = events
        self.rrf_k = rrf_k
        self.reranker = reranker
        self.last_error: str | None = None
        self._retry_at = 0.0
        self._initialized = False

    @contextmanager
    def connection(self, *, vectors: bool = False) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=15000")
            db.execute("PRAGMA secure_delete=ON")
            if not self._initialized:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    raise ValueError("Unsupported semantic DB schema")
                db.executescript(_SCHEMA)
                self._initialized = True
            if vectors:
                import sqlite_vec  # type: ignore[import-untyped]

                db.enable_load_extension(True)
                try:
                    sqlite_vec.load(db)
                finally:
                    db.enable_load_extension(False)
            with db:
                yield db
        finally:
            db.close()

    def _failed(self, error: Exception) -> None:
        self.last_error = type(error).__name__
        self._retry_at = time.monotonic() + 30
        if self.events:
            self.events.emit(
                "rag.semantic_unavailable",
                {
                    "error_type": self.last_error,
                    "fallback": "fts5",
                    "model": self.settings.model,
                },
            )

    @staticmethod
    def _upsert(
        db: sqlite3.Connection,
        key: str,
        kind: str,
        group: str,
        text: str,
        metadata: Mapping[str, Any],
    ) -> None:
        db.execute(
            """INSERT INTO semantic_items(id,kind,group_id,text,metadata) VALUES(?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,group_id=excluded.group_id,
            metadata=excluded.metadata,text=excluded.text,
            model=CASE WHEN semantic_items.text=excluded.text
                AND semantic_items.metadata=excluded.metadata THEN model ELSE NULL END,
            dim=CASE WHEN semantic_items.text=excluded.text
                AND semantic_items.metadata=excluded.metadata THEN dim ELSE NULL END,
            vector=CASE WHEN semantic_items.text=excluded.text
                AND semantic_items.metadata=excluded.metadata THEN vector ELSE NULL END
            WHERE semantic_items.text!=excluded.text
               OR semantic_items.metadata!=excluded.metadata""",
            (key, kind, group, text, json.dumps(dict(metadata), ensure_ascii=False)),
        )

    def sync_documents(self, rows: Sequence[Mapping[str, Any]]) -> None:
        """Reconcile the authoritative document snapshot, including removals."""
        with self.connection() as db:
            existing = {
                r[0] for r in db.execute("SELECT id FROM semantic_items WHERE kind='document'")
            }
            current = set()
            for row in rows:
                key = "doc:" + str(row["chunk_id"])
                current.add(key)
                self._upsert(
                    db,
                    key,
                    "document",
                    str(row["doc_id"]),
                    str(row["text"]),
                    {k: v for k, v in row.items() if k != "text"},
                )
            db.executemany(
                "DELETE FROM semantic_items WHERE id=?", [(k,) for k in existing - current]
            )
        self._index_pending(kind="document")

    def _index_pending(self, *, kind: str | None = None, limit: int | None = None) -> int:
        if not self.settings.enabled or time.monotonic() < self._retry_at:
            return 0
        indexed = 0
        try:
            with self.connection() as db:
                if not db.execute("SELECT 1 FROM semantic_items LIMIT 1").fetchone():
                    return 0
            model = retrieval_identity(self.embedder)
            with self.connection(vectors=True) as db:
                query = (
                    "SELECT id,text,metadata FROM semantic_items WHERE (model IS NULL OR model!=?)"
                )
                params: list[Any] = [model]
                if kind:
                    query += " AND kind=?"
                    params.append(kind)
                if limit:
                    query += " LIMIT ?"
                    params.append(limit)
                rows = db.execute(query, params).fetchall()
            # Never hold a SQLite write transaction during model inference.
            for row in rows:
                metadata = json.loads(row["metadata"])
                title = str(
                    metadata.get("title", metadata.get("path", metadata.get("source_path", "none")))
                )
                vec = embed_document(self.embedder, row["text"], title)
                blob = struct.pack(f"<{len(vec)}f", *vec)
                with self.connection() as db:
                    db.execute(
                        "UPDATE semantic_items SET model=?,dim=?,vector=? "
                        "WHERE id=? AND text=? AND metadata=?",
                        (model, len(vec), blob, row["id"], row["text"], row["metadata"]),
                    )
                indexed += 1
            self.last_error = None
        except Exception as error:
            self._failed(error)
        return indexed

    def _vector_ranking(
        self, text: str, *, document: bool, limit: int, exclude_turn_id: str = ""
    ) -> list[str]:
        if not self.settings.enabled or time.monotonic() < self._retry_at:
            return []
        try:
            # Empty indexes must not trigger model startup.
            with self.connection() as db:
                operator = "=" if document else "!="
                if not db.execute(
                    f"SELECT 1 FROM semantic_items WHERE kind{operator}'document' LIMIT 1"
                ).fetchone():
                    return []
            model = retrieval_identity(self.embedder)
            vec = embed_query(self.embedder, text)
            with self.connection(vectors=True) as db:
                rows = db.execute(
                    f"""SELECT id,vec_distance_cosine(vector,?) AS distance FROM semantic_items
                    WHERE kind{operator}'document' AND model=? AND dim=? AND group_id!=?
                    AND vector IS NOT NULL ORDER BY distance,id LIMIT ?""",
                    (struct.pack(f"<{len(vec)}f", *vec), model, len(vec), exclude_turn_id, limit),
                ).fetchall()
            self.last_error = None
            return [
                str(r["id"])
                for r in rows
                if 1 - float(r["distance"]) >= self.settings.min_similarity
            ]
        except Exception as error:
            self._failed(error)
            return []

    def document_ranking(self, query: str, *, limit: int) -> list[str]:
        return [
            key.removeprefix("doc:")
            for key in self._vector_ranking(query, document=True, limit=limit)
        ]

    def search_document_vector(
        self, vector: list[float], *, model: str, limit: int
    ) -> list[tuple[str, float]]:
        """Strict vector-only query for benchmarks: failures must not look like scores."""
        vec = normalized_vector(vector)
        with self.connection(vectors=True) as db:
            rows = db.execute(
                """SELECT id,vec_distance_cosine(vector,?) AS distance FROM semantic_items
                WHERE kind='document' AND model=? AND dim=? AND vector IS NOT NULL
                ORDER BY distance,id LIMIT ?""",
                (struct.pack(f"<{len(vec)}f", *vec), model, len(vec), limit),
            ).fetchall()
        return [(r["id"].removeprefix("doc:"), 1 - float(r["distance"])) for r in rows]

    def remember_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        question: str,
        answer: str,
        created_at: datetime,
        sources: Sequence[str] = (),
        model: str = "",
        answer_mode: str | None = None,
        fallback_reason: str | None = None,
    ) -> None:
        if not self.settings.conversations_enabled:
            return
        self.prune(created_at)
        metadata = {
            "sources": list(sources),
            "verified": False,
            "model": model,
            "answer_mode": answer_mode,
            "fallback_reason": fallback_reason,
        }
        with self.connection() as db:
            db.execute(
                """INSERT INTO conversation_turns VALUES(?,?,?,?,?,?)
                ON CONFLICT(turn_id) DO UPDATE SET question=excluded.question,
                answer=excluded.answer,metadata=excluded.metadata""",
                (
                    turn_id,
                    session_id,
                    question,
                    answer,
                    created_at.isoformat(),
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
            # A turn is a linked pair; long messages get separate searchable chunks.
            keep = set()
            for kind, text in (("question", question), ("answer", answer)):
                for chunk in chunk_text(text, chunk_chars=1200, overlap_chars=100):
                    key = f"turn:{turn_id}:{kind}:{chunk.ordinal}"
                    keep.add(key)
                    self._upsert(
                        db,
                        key,
                        kind,
                        turn_id,
                        chunk.text,
                        {
                            **metadata,
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "created_at": created_at.isoformat(),
                            "ordinal": chunk.ordinal,
                        },
                    )
            old = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM semantic_items WHERE group_id=? AND kind!='document'",
                    (turn_id,),
                )
            ]
            db.executemany(
                "DELETE FROM semantic_items WHERE id=?", [(key,) for key in old if key not in keep]
            )
        self._index_pending(limit=64)

    def recall(
        self, query: str, *, now: datetime, exclude_turn_id: str = "", limit: int | None = None
    ) -> list[dict[str, Any]]:
        if not self.settings.conversations_enabled or not query.strip():
            return []
        self.prune(now)
        limit = limit or self.settings.conversation_top_k
        candidate_limit = limit * 4
        if self.reranker is not None:
            candidate_limit = self.reranker.retrieval_limit(candidate_limit)
        with self.connection() as db:
            lexical = [
                r[0]
                for r in db.execute(
                    """SELECT i.id FROM semantic_fts f JOIN semantic_items i ON i.rowid=f.rowid
                WHERE semantic_fts MATCH ? AND i.kind!='document' AND i.group_id!=?
                ORDER BY bm25(semantic_fts),i.id LIMIT ?""",
                    (_fts_query(query), exclude_turn_id, candidate_limit),
                )
            ]
        self._index_pending(kind="question", limit=16)
        self._index_pending(kind="answer", limit=16)
        vectors = self._vector_ranking(
            query, document=False, limit=candidate_limit, exclude_turn_id=exclude_turn_id
        )
        ranked = reciprocal_rank_fusion([lexical, vectors], k=self.rrf_k)
        results: list[dict[str, Any]] = []
        by_turn: dict[str, dict[str, Any]] = {}
        with self.connection() as db:
            for key, score in ranked:
                row = db.execute(
                    """SELECT t.*,i.text AS matched_text,i.kind AS matched_kind
                    FROM conversation_turns t JOIN semantic_items i
                    ON i.group_id=t.turn_id WHERE i.id=?""",
                    (key,),
                ).fetchone()
                if row is None:
                    continue
                existing = by_turn.get(row["turn_id"])
                if existing is not None:
                    if existing["matched_kind"] != "answer" and row["matched_kind"] == "answer":
                        existing["matched_text"] = row["matched_text"]
                        existing["matched_kind"] = "answer"
                    continue
                result = {**dict(row), **json.loads(row["metadata"]), "score": score}
                by_turn[row["turn_id"]] = result
                results.append(result)
        if self.reranker is not None:
            # Keep unique pairs, with the matching excerpt instead of just the start
            # of a long answer/question. Original messages remain unchanged in storage.
            candidates = [
                Candidate(
                    r["turn_id"],
                    (
                        "Question: "
                        + (r["matched_text"] if r["matched_kind"] == "question" else r["question"])[
                            :400
                        ]
                        + "\nAnswer: "
                        + (r["matched_text"] if r["matched_kind"] == "answer" else r["answer"])[
                            :1600
                        ]
                    ),
                    r["score"],
                )
                for r in results
            ]
            reranked = self.reranker.rank(query, candidates)
            by_id = {r["turn_id"]: r for r in results}
            results = [{**by_id[c.key], "rerank_score": c.rerank_score} for c in reranked]
        return results[:limit]

    def forget_turn(self, turn_id: str) -> None:
        with self.connection() as db:
            db.execute(
                "DELETE FROM semantic_items WHERE group_id=? AND kind!='document'", (turn_id,)
            )
            db.execute("DELETE FROM conversation_turns WHERE turn_id=?", (turn_id,))

    def prune(self, now: datetime) -> None:
        cutoff = (now - timedelta(days=self.settings.retention_days)).isoformat()
        with self.connection() as db:
            db.execute(
                """DELETE FROM semantic_items WHERE kind!='document' AND group_id IN
                (SELECT turn_id FROM conversation_turns
                 WHERE julianday(created_at)<julianday(?))""",
                (cutoff,),
            )
            db.execute(
                "DELETE FROM conversation_turns WHERE julianday(created_at)<julianday(?)", (cutoff,)
            )

    def reindex(self) -> int:
        self._retry_at = 0
        return self._index_pending()

    def stats(self) -> dict[str, Any]:
        with self.connection() as db:
            return {
                "documents": db.execute(
                    "SELECT count(*) FROM semantic_items WHERE kind='document'"
                ).fetchone()[0],
                "turns": db.execute("SELECT count(*) FROM conversation_turns").fetchone()[0],
                "vectors": db.execute(
                    "SELECT count(*) FROM semantic_items WHERE vector IS NOT NULL"
                ).fetchone()[0],
                "conversation_vectors": db.execute(
                    "SELECT count(*) FROM semantic_items WHERE kind!='document' "
                    "AND vector IS NOT NULL"
                ).fetchone()[0],
                "pending_vectors": db.execute(
                    "SELECT count(*) FROM semantic_items WHERE vector IS NULL"
                ).fetchone()[0],
                "last_error": self.last_error,
                "rerank_status": self.reranker.status if self.reranker else "not_configured",
                "rerank_error": self.reranker.last_error if self.reranker else None,
            }

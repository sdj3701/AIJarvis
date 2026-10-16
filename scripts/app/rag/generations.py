"""Prepare immutable document generations; publish text/FTS/vectors atomically.

The document search snapshot lives in the primary SQLite DB. semantic.sqlite3 is
a recoverable projection for compatibility and conversation recall, not a second
commit point for document retrieval. A failed prepare never changes active rows.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.rag.chunker import DOCUMENT_CHUNK_POLICY, document_chunks
from app.rag.document_parser import PARSER_POLICY, ParsedDocument, PDFNeedsOCR, parse_document
from app.rag.local_embedder import embed_document, embed_query, retrieval_identity
from app.rag.markdown_exports import export_root, sync_markdown_exports
from app.rag.models import IndexReport

if TYPE_CHECKING:
    from app.rag.indexer import DocumentIndexer

SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_generations (
    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, model TEXT NOT NULL,
    state TEXT NOT NULL, created_at TEXT NOT NULL, snapshot TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rag_index_state (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), active_generation TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rag_generation_vectors (
    generation TEXT NOT NULL, chunk_id TEXT NOT NULL, model TEXT NOT NULL,
    dim INTEGER NOT NULL, vector BLOB NOT NULL,
    PRIMARY KEY(generation,chunk_id)
);
CREATE TABLE IF NOT EXISTS rag_chunk_provenance (
    chunk_id TEXT PRIMARY KEY, generation TEXT NOT NULL, title TEXT NOT NULL,
    token_count INTEGER, tokenizer_id TEXT NOT NULL, document_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rag_document_content (
    doc_id TEXT PRIMARY KEY, parser TEXT NOT NULL, source_hash TEXT NOT NULL,
    markdown TEXT NOT NULL, metadata TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rag_chunk_structure (
    chunk_id TEXT PRIMARY KEY, pages TEXT NOT NULL, structure TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rag_markdown_exports (
    doc_id TEXT PRIMARY KEY, path TEXT NOT NULL, sha256 TEXT NOT NULL
);
"""


class GenerationIndex:
    def __init__(self, indexer: DocumentIndexer):
        self.indexer = indexer
        with indexer._connection() as db:
            db.executescript(SCHEMA)

    def active(self) -> dict[str, Any] | None:
        with self.indexer._connection() as db:
            row = db.execute("""SELECT g.* FROM rag_generations g JOIN rag_index_state s
                ON g.id=s.active_generation WHERE s.singleton=1""").fetchone()
        return dict(row) if row else None

    def sync(self, *, now: datetime | None = None) -> IndexReport:
        ix = self.indexer
        ix.docs_root.mkdir(parents=True, exist_ok=True)
        active = self.active()
        errors: list[str] = []
        with ix._connection() as db:
            existing = {r["path"]: dict(r) for r in db.execute("SELECT * FROM documents")}
            cached = {
                r["doc_id"]: dict(r) for r in db.execute("SELECT * FROM rag_document_content")
            }
        documents: list[dict[str, Any]] = []
        contents: dict[str, ParsedDocument] = {}
        parser_identity = (
            f"{PARSER_POLICY}:{ix.settings.pdf_max_pages}:{ix.settings.pdf_max_characters}"
        )
        seen = set()
        for path in sorted(ix._iter_files()):
            rel = ""
            try:
                rel = ix._relative_path(path)
                seen.add(rel)
                if path.stat().st_size > ix.settings.max_file_bytes:
                    raise ValueError("문서 크기 한도 초과")
                raw = path.read_bytes()
                if len(raw) > ix.settings.max_file_bytes:
                    raise ValueError("문서 크기 한도 초과")
                previous = existing.get(rel)
                source_hash = hashlib.sha256(raw).hexdigest()
                saved = cached.get(previous["doc_id"]) if previous else None
                if (
                    saved
                    and saved["source_hash"] == source_hash
                    and saved["parser"] == parser_identity
                ):
                    metadata = json.loads(saved["metadata"])
                    contents[rel] = ParsedDocument.from_snapshot(
                        {
                            **metadata,
                            "markdown": saved["markdown"],
                            "source_hash": source_hash,
                        }
                    )
                else:
                    contents[rel] = parse_document(
                        raw,
                        path.suffix,
                        max_pages=ix.settings.pdf_max_pages,
                        max_characters=ix.settings.pdf_max_characters,
                    )
                documents.append(
                    {
                        "doc_id": previous["doc_id"] if previous else ix.ids.new("doc"),
                        "path": rel,
                        "content_hash": source_hash,
                        "transfer_class": ix._transfer_class(rel),
                        "bytes": len(raw),
                    }
                )
            except Exception as error:
                # No document text or untrusted exception message enters diagnostics.
                label = (
                    "PDF OCR 필요"
                    if isinstance(error, PDFNeedsOCR)
                    else "PDF 읽기 실패"
                    if path.suffix.lower() == ".pdf"
                    else "문서 읽기 실패"
                )
                errors.append(f"{rel or path.name}: {label} ({type(error).__name__})")
        # Read failures must not remove a formerly indexed document.
        if any(p in existing and p not in contents for p in seen):
            ix.last_diagnostics["source_stale"] = True
            return IndexReport(0, 0, 0, len(existing), tuple(errors))
        model = ""
        counter = None
        if ix.semantic and ix.settings.semantic.enabled and (documents or active):
            try:
                refresh = getattr(ix.semantic.embedder, "refresh_identity", None)
                if refresh:
                    refresh()
                model = retrieval_identity(ix.semantic.embedder)
                counter = getattr(ix.semantic.embedder, "count_document_tokens", None)
            except Exception as error:
                ix.semantic._failed(error)
                errors.append("벡터 모델 대기: " + type(error).__name__)
        policy = {
            "parser": parser_identity,
            "chunker": DOCUMENT_CHUNK_POLICY,
            "model": model,
            "max_chars": ix.settings.chunk_chars,
            "overlap_chars": ix.settings.chunk_overlap_chars,
            "max_tokens": ix.settings.chunk_max_tokens,
            "overlap_tokens": ix.settings.chunk_overlap_tokens,
            "counter": model if counter else "lexical-character-bound",
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                {"policy": policy, "documents": documents},
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        if active and active["fingerprint"] == fingerprint:
            ix.last_diagnostics["source_stale"] = False
            self.repair_projection(active["id"], errors)
            self.repair_markdown_exports(errors)
            return IndexReport(0, 0, 0, len(documents), tuple(errors))
        # A model outage must not replace a working vector generation with a
        # different representation. Readers can still use its lexical snapshot.
        if active and active["model"] and not model and ix.settings.semantic.enabled:
            before = {
                d["path"]: d["content_hash"] for d in json.loads(active["snapshot"])["documents"]
            }
            ix.last_diagnostics["source_stale"] = before != {
                d["path"]: d["content_hash"] for d in documents
            }
            return IndexReport(0, 0, 0, len(existing), tuple(errors))
        chunks = []
        vectors = []
        timestamp = (now or datetime.now().astimezone()).isoformat(timespec="milliseconds")
        generation = ix.ids.new("gen")
        old_snapshot = json.loads(active["snapshot"]) if active else {}
        same_policy = old_snapshot.get("policy") == policy
        old_chunks = old_snapshot.get("chunks", [])
        old_vectors = {}
        if active and same_policy:
            with ix._connection() as db:
                old_vectors = {
                    r["chunk_id"]: dict(r)
                    for r in db.execute(
                        "SELECT * FROM rag_generation_vectors WHERE generation=?", (active["id"],)
                    )
                }
        try:
            for doc in documents:
                doc["indexed_at"] = timestamp
                parsed = contents[doc["path"]]
                doc["parsed"] = parsed.snapshot()
                prior = existing.get(doc["path"])
                reusable = (
                    same_policy
                    and prior
                    and prior["content_hash"] == doc["content_hash"]
                    and prior["transfer_class"] == doc["transfer_class"]
                )
                parts = [c for c in old_chunks if c["doc_id"] == doc["doc_id"]] if reusable else []
                if not reusable:
                    parts = []
                    for c in document_chunks(
                        parsed.markdown,
                        title=doc["path"],
                        count_tokens=counter,
                        tokenizer_id=model if counter else "lexical-character-bound",
                        max_tokens=ix.settings.chunk_max_tokens,
                        overlap_tokens=ix.settings.chunk_overlap_tokens,
                        max_chars=ix.settings.chunk_chars,
                        overlap_chars=ix.settings.chunk_overlap_chars,
                    ):
                        parts.append(
                            {
                                "chunk_id": ix.ids.new("chk"),
                                "doc_id": doc["doc_id"],
                                "ordinal": c.ordinal,
                                "text": c.text,
                                "start_char": c.start_char,
                                "end_char": c.end_char,
                                "title": c.title,
                                "token_count": c.token_count,
                                "tokenizer_id": c.tokenizer_id,
                                "document_hash": doc["content_hash"],
                                **parsed.chunk_metadata(c.start_char, c.end_char),
                            }
                        )
                doc["chunk_count"] = len(parts)
                chunks.extend(parts)
                if model and ix.semantic:
                    for c in parts:
                        old = old_vectors.get(c["chunk_id"])
                        if old:
                            vectors.append(
                                (generation, c["chunk_id"], model, old["dim"], old["vector"])
                            )
                        else:
                            v = embed_document(ix.semantic.embedder, c["text"], c["title"])
                            vectors.append(
                                (
                                    generation,
                                    c["chunk_id"],
                                    model,
                                    len(v),
                                    struct.pack(f"<{len(v)}f", *v),
                                )
                            )
            if vectors and len({v[3] for v in vectors}) != 1:
                raise ValueError("Mixed vector dimensions")
        except Exception as error:
            if ix.semantic:
                ix.semantic._failed(error)
            errors.append("새 색인 준비 실패; 이전 색인 유지: " + type(error).__name__)
            ix.last_diagnostics["source_stale"] = True
            return IndexReport(0, 0, 0, len(existing), tuple(errors))
        snapshot = json.dumps(
            {"documents": documents, "chunks": chunks, "policy": policy}, ensure_ascii=False
        )
        # Two transactions: prepared rows are invisible until the pointer and all
        # authoritative document rows switch in the second transaction.
        with ix._connection() as db, db:
            db.execute(
                "INSERT INTO rag_generations VALUES(?,?,?,?,?,?)",
                (generation, fingerprint, model, "prepared", timestamp, snapshot),
            )
            db.executemany("INSERT INTO rag_generation_vectors VALUES(?,?,?,?,?)", vectors)
        self.publish(generation, expected=active["id"] if active else None)
        ix.last_diagnostics["source_stale"] = False
        self.repair_projection(generation, errors)
        self.repair_markdown_exports(errors)
        new = sum(d["path"] not in existing for d in documents)
        changed = sum(
            d["path"] in existing
            and (
                not same_policy
                or d["content_hash"] != existing[d["path"]]["content_hash"]
                or d["transfer_class"] != existing[d["path"]]["transfer_class"]
            )
            for d in documents
        )
        removed = len(set(existing) - {d["path"] for d in documents})
        return IndexReport(new, changed, removed, len(documents) - new - changed, tuple(errors))

    def repair_markdown_exports(self, errors: list[str]) -> None:
        try:
            with self.indexer._connection() as db, db:
                db.execute("BEGIN IMMEDIATE")
                sync_markdown_exports(db, export_root(self.indexer.database_path), errors)
        except (OSError, ValueError, sqlite3.Error) as error:
            errors.append("Markdown 파일 동기화 대기: " + type(error).__name__)

    def repair_projection(self, generation: str, errors: list[str]) -> None:
        ix = self.indexer
        if ix.semantic is None:
            return
        try:
            with ix.semantic.connection() as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS document_projection "
                    "(singleton INTEGER PRIMARY KEY, generation TEXT NOT NULL)"
                )
                row = db.execute(
                    "SELECT generation FROM document_projection WHERE singleton=1"
                ).fetchone()
            if row and row[0] == generation and not ix.semantic.last_error:
                return
            # This explicit repair follows a successful canonical publication;
            # an earlier retry delay must not mark an unbuilt projection current.
            ix.semantic._retry_at = 0
            ix.sync_vectors()
            if ix.semantic.last_error:
                errors.append("문서 사본 복구 대기: " + ix.semantic.last_error)
                return
            with ix.semantic.connection() as db:
                db.execute("INSERT OR REPLACE INTO document_projection VALUES(1,?)", (generation,))
        except Exception as error:
            ix.semantic._failed(error)
            errors.append("문서 사본 복구 대기: " + type(error).__name__)

    def publish(self, generation: str, *, expected: str | None) -> None:
        ix = self.indexer
        with ix._connection() as db, db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT active_generation FROM rag_index_state").fetchone()
            if (current[0] if current else None) != expected:
                raise RuntimeError("Index changed while generation was prepared; retry sync")
            row = db.execute(
                "SELECT snapshot,model FROM rag_generations WHERE id=?", (generation,)
            ).fetchone()
            if row is None:
                raise ValueError("Unknown generation")
            snapshot = json.loads(row[0])
            if row[1]:
                ids = {
                    r[0]
                    for r in db.execute(
                        "SELECT chunk_id FROM rag_generation_vectors "
                        "WHERE generation=? AND model=?",
                        (generation, row[1]),
                    )
                }
                if ids != {c["chunk_id"] for c in snapshot["chunks"]}:
                    raise ValueError("Incomplete generation vectors")
            db.execute("DELETE FROM doc_chunks")
            db.execute("DELETE FROM documents")
            db.execute("DELETE FROM rag_chunk_provenance")
            db.execute("DELETE FROM rag_chunk_structure")
            db.execute("DELETE FROM rag_document_content")
            for d in snapshot["documents"]:
                db.execute(
                    "INSERT INTO documents VALUES(?,?,?,?,?,?,?)",
                    (
                        d["doc_id"],
                        d["path"],
                        d["content_hash"],
                        d["transfer_class"],
                        d["indexed_at"],
                        d["bytes"],
                        d["chunk_count"],
                    ),
                )
                if parsed := d.get("parsed"):
                    metadata = {
                        k: v for k, v in parsed.items() if k not in {"markdown", "source_hash"}
                    }
                    db.execute(
                        "INSERT INTO rag_document_content VALUES(?,?,?,?,?)",
                        (
                            d["doc_id"],
                            snapshot["policy"]["parser"],
                            parsed["source_hash"],
                            parsed["markdown"],
                            json.dumps(metadata, ensure_ascii=False),
                        ),
                    )
            for c in snapshot["chunks"]:
                db.execute(
                    "INSERT INTO doc_chunks VALUES(?,?,?,?,?,?)",
                    (
                        c["chunk_id"],
                        c["doc_id"],
                        c["ordinal"],
                        c["text"],
                        c["start_char"],
                        c["end_char"],
                    ),
                )
                db.execute(
                    "INSERT INTO rag_chunk_provenance VALUES(?,?,?,?,?,?)",
                    (
                        c["chunk_id"],
                        generation,
                        c["title"],
                        c["token_count"],
                        c["tokenizer_id"],
                        c["document_hash"],
                    ),
                )
                db.execute(
                    "INSERT INTO rag_chunk_structure VALUES(?,?,?)",
                    (
                        c["chunk_id"],
                        json.dumps(c.get("pages", [])),
                        json.dumps(c.get("structure", []), ensure_ascii=False),
                    ),
                )
            db.execute("UPDATE rag_generations SET state='retired' WHERE state='active'")
            db.execute("UPDATE rag_generations SET state='active' WHERE id=?", (generation,))
            db.execute("INSERT OR REPLACE INTO rag_index_state VALUES(1,?)", (generation,))
            # Keep the prior complete generation for explicit rollback. A deletion
            # purges old generations so deleted source content cannot be revived.
            keep = [generation]
            if expected:
                old = db.execute(
                    "SELECT snapshot FROM rag_generations WHERE id=?", (expected,)
                ).fetchone()
                old_paths = {d["path"] for d in json.loads(old[0])["documents"]} if old else set()
                if old_paths <= {d["path"] for d in snapshot["documents"]}:
                    keep.append(expected)
            marks = ",".join("?" for _ in keep)
            db.execute(
                f"DELETE FROM rag_generation_vectors WHERE generation NOT IN ({marks})", keep
            )
            db.execute(f"DELETE FROM rag_generations WHERE id NOT IN ({marks})", keep)

    def vector_ranking(self, query: str, *, limit: int, db: sqlite3.Connection) -> list[str]:
        ix = self.indexer
        if not ix.semantic or not ix.settings.semantic.enabled:
            return []
        row = db.execute("""SELECT s.active_generation,g.model FROM rag_index_state s
            JOIN rag_generations g ON g.id=s.active_generation""").fetchone()
        if not row:
            return []
        if not db.execute("SELECT 1 FROM doc_chunks LIMIT 1").fetchone():
            return []
        model = retrieval_identity(ix.semantic.embedder)
        if row[1] != model:
            raise ValueError("Active generation requires model/prompt reindex")
        vector = embed_query(ix.semantic.embedder, query)
        import sqlite_vec  # type: ignore[import-untyped]

        db.enable_load_extension(True)
        try:
            sqlite_vec.load(db)
        finally:
            db.enable_load_extension(False)
        rows = db.execute(
            """SELECT chunk_id, vec_distance_cosine(vector,?) AS distance
            FROM rag_generation_vectors WHERE generation=? AND model=? AND dim=?
            ORDER BY distance,chunk_id LIMIT ?""",
            (struct.pack(f"<{len(vector)}f", *vector), row[0], model, len(vector), limit),
        ).fetchall()
        ix.semantic.last_error = None
        return [
            r["chunk_id"]
            for r in rows
            if 1 - float(r["distance"]) >= ix.settings.semantic.min_similarity
        ]

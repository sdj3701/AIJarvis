"""Local document indexing and FTS search."""

from __future__ import annotations

import fnmatch
import hashlib
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from app.config.models import DocumentPolicy, RagSettings
from app.core.errors import ConfigError, JarvisError
from app.core.ids import PrefixedIdFactory
from app.memory.migrations import configure_connection
from app.rag.chunker import chunk_text
from app.rag.models import IndexReport, RetrievedChunk


class EventSink(Protocol):
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class DocumentIndexer:
    database_path: Path
    docs_root: Path
    settings: RagSettings
    document_policy: DocumentPolicy
    ids: PrefixedIdFactory
    events: EventSink | None = None

    def sync(self, *, now: datetime | None = None) -> IndexReport:
        indexed_at = (now or datetime.now().astimezone()).isoformat(timespec="milliseconds")
        self.docs_root.mkdir(parents=True, exist_ok=True)
        indexed = updated = removed = skipped = 0
        errors: list[str] = []
        seen_paths: set[str] = set()

        for path in sorted(self._iter_files()):
            rel = self._relative_path(path)
            seen_paths.add(rel.replace("/", "\\"))
            try:
                action = self._sync_file(path, rel, indexed_at=indexed_at)
            except JarvisError as error:
                errors.append(f"{rel}: {error.user_message}")
                continue
            if action == "indexed":
                indexed += 1
            elif action == "updated":
                updated += 1
            else:
                skipped += 1

        removed += self._remove_missing(seen_paths)
        report = IndexReport(
            indexed=indexed,
            updated=updated,
            removed=removed,
            skipped=skipped,
            errors=tuple(errors),
        )
        if self.events is not None:
            self.events.emit(
                "rag.index",
                {
                    "indexed": report.indexed,
                    "updated": report.updated,
                    "removed": report.removed,
                    "skipped": report.skipped,
                    "errors": list(report.errors),
                },
            )
        return report

    def search(
        self,
        query: str,
        *,
        max_results: int | None = None,
        max_chunks: int | None = None,
    ) -> tuple[RetrievedChunk, ...]:
        limit = max_results or self.settings.search.max_results
        chunk_limit = max_chunks or self.settings.max_chunks_per_answer
        fts_query = _fts_query(query)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    dc.chunk_id,
                    dc.doc_id,
                    d.path,
                    dc.ordinal,
                    dc.text,
                    dc.start_char,
                    dc.end_char,
                    d.transfer_class,
                    bm25(doc_chunks_fts) AS score
                FROM doc_chunks_fts
                JOIN doc_chunks dc ON doc_chunks_fts.rowid = dc.rowid
                JOIN documents d ON d.doc_id = dc.doc_id
                WHERE doc_chunks_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (fts_query, limit * 3),
            ).fetchall()

        hits: list[RetrievedChunk] = []
        seen_docs: dict[str, int] = {}
        for row in rows:
            doc_id = str(row["doc_id"])
            if seen_docs.get(doc_id, 0) >= 2:
                continue
            chunk = RetrievedChunk(
                chunk_id=str(row["chunk_id"]),
                doc_id=doc_id,
                relative_path=str(row["path"]),
                ordinal=int(row["ordinal"]),
                text=str(row["text"]),
                start_char=int(row["start_char"]),
                end_char=int(row["end_char"]),
                transfer_class=row["transfer_class"],
                score=float(row["score"]),
            )
            hits.append(chunk)
            seen_docs[doc_id] = seen_docs.get(doc_id, 0) + 1
            if len(hits) >= chunk_limit:
                break
        return tuple(hits)

    def _sync_file(
        self,
        path: Path,
        rel: str,
        *,
        indexed_at: str,
    ) -> Literal["indexed", "updated", "skipped"]:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            raise ConfigError(
                "PDF 형식은 아직 지원하지 않습니다. .md 또는 .txt 파일을 사용하세요.",
                {"path": rel},
            )
        if suffix not in {ext.lower() for ext in self.settings.supported_extensions}:
            raise ConfigError(
                f"지원하지 않는 문서 형식입니다: {suffix or '(없음)'}",
                {"path": rel},
            )
        size = path.stat().st_size
        if size > self.settings.max_file_bytes:
            raise ConfigError(
                "문서 크기가 설정 한도를 초과했습니다.",
                {"path": rel, "bytes": size},
            )
        content = path.read_text(encoding="utf-8")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        transfer_class = self._transfer_class(rel)

        with self._connection() as connection, connection:
            existing = connection.execute(
                "SELECT doc_id, content_hash FROM documents WHERE path = ?",
                (rel.replace("/", "\\"),),
            ).fetchone()
            if existing is not None and str(existing["content_hash"]) == content_hash:
                return "skipped"

            doc_id = str(existing["doc_id"]) if existing is not None else self.ids.new("doc")
            if existing is not None:
                connection.execute("DELETE FROM doc_chunks WHERE doc_id = ?", (doc_id,))
                connection.execute(
                    """
                    UPDATE documents
                    SET content_hash = ?, transfer_class = ?, indexed_at = ?,
                        bytes = ?, chunk_count = ?
                    WHERE doc_id = ?
                    """,
                    (content_hash, transfer_class, indexed_at, size, 0, doc_id),
                )
                action: Literal["indexed", "updated", "skipped"] = "updated"
            else:
                connection.execute(
                    """
                    INSERT INTO documents(
                        doc_id, path, content_hash, transfer_class, indexed_at, bytes, chunk_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        rel.replace("/", "\\"),
                        content_hash,
                        transfer_class,
                        indexed_at,
                        size,
                        0,
                    ),
                )
                action = "indexed"

            chunks = chunk_text(
                content,
                chunk_chars=self.settings.chunk_chars,
                overlap_chars=self.settings.chunk_overlap_chars,
            )
            for chunk in chunks:
                chunk_id = self.ids.new("chk")
                connection.execute(
                    """
                    INSERT INTO doc_chunks(chunk_id, doc_id, ordinal, text, start_char, end_char)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (chunk_id, doc_id, chunk.ordinal, chunk.text, chunk.start_char, chunk.end_char),
                )
            connection.execute(
                "UPDATE documents SET chunk_count = ? WHERE doc_id = ?",
                (len(chunks), doc_id),
            )
            return action

    def _remove_missing(self, seen_paths: set[str]) -> int:
        removed = 0
        with self._connection() as connection, connection:
            rows = connection.execute("SELECT doc_id, path FROM documents").fetchall()
            for row in rows:
                path = str(row["path"])
                if path not in seen_paths:
                    connection.execute("DELETE FROM documents WHERE doc_id = ?", (row["doc_id"],))
                    removed += 1
        return removed

    def _iter_files(self) -> Iterable[Path]:
        extensions = {ext.lower() for ext in self.settings.supported_extensions}
        for path in self.docs_root.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix == ".pdf" or suffix in extensions:
                yield path

    def _relative_path(self, path: Path) -> str:
        root = self.docs_root.resolve(strict=False)
        resolved = path.resolve(strict=False)
        try:
            rel = resolved.relative_to(root)
        except ValueError as error:
            raise ConfigError("문서 경로가 docs root 밖입니다.", {"path": str(path)}) from error
        return str(rel).replace("/", "\\")

    def _transfer_class(self, relative_path: str) -> Literal["local_only", "api_allowed"]:
        normalized = relative_path.replace("/", "\\")
        candidates = (normalized, f"docs\\{normalized}")
        for rule in self.document_policy.class_rules:
            pattern = rule.match.replace("/", "\\")
            for candidate in candidates:
                if fnmatch.fnmatch(candidate, pattern):
                    return rule.classification
        return self.document_policy.default_class

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        configure_connection(connection)
        return connection


def _fts_query(text: str) -> str:
    tokens = [token for token in text.split() if token.strip()]
    if not tokens:
        return '""'
    return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)

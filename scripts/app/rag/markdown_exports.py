"""Recoverable UTF-8 PDF exports derived only from committed document content."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath


def export_root(database_path: Path) -> Path:
    return database_path.parent / (database_path.stem + "-pdf-markdown")


def _checked_path(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    if (
        len(parts) != 2
        or not re.fullmatch(r"[A-Za-z0-9_-]+", parts[0])
        or PureWindowsPath(parts[1]).name != parts[1]
        or not parts[1].endswith(".md")
    ):
        raise ValueError("Invalid managed Markdown path")
    target = root.joinpath(*parts)
    # Reject redirected managed directories/files, including Windows junctions.
    for path in (root, target.parent, target):
        if path.is_symlink() or (
            path.exists()
            and getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("Redirected Markdown path")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Markdown path escapes export directory")
    return target


def _write_complete(path: Path, data: bytes) -> None:
    """An interrupted replacement leaves either the previous or complete new file."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def sync_markdown_exports(db: sqlite3.Connection, root: Path, errors: list[str]) -> None:
    """Caller holds BEGIN IMMEDIATE so publishers cannot change the source snapshot.

    Files are a projection, not a second commit requirement for retrieval. Record
    ownership before writing so a failed write or later removal remains retryable.
    """
    rows = db.execute("""SELECT d.doc_id,d.path,c.markdown FROM documents d
        JOIN rag_document_content c USING(doc_id)""").fetchall()
    pdfs = [r for r in rows if PureWindowsPath(r["path"]).suffix.lower() == ".pdf"]
    expected = {r["doc_id"] for r in pdfs}
    for row in pdfs:
        try:
            # Separate document IDs prevent same-named PDFs from overwriting each other.
            stem = PureWindowsPath(row["path"]).stem[:100]
            relative = f"{row['doc_id']}/{stem}.md"
            target = _checked_path(root, relative)
            data = row["markdown"].encode("utf-8")
            digest = hashlib.sha256(data).hexdigest()
            owned = db.execute(
                "SELECT path FROM rag_markdown_exports WHERE doc_id=?", (row["doc_id"],)
            ).fetchone()
            if target.exists() and owned is None and target.read_bytes() != data:
                raise FileExistsError("Unmanaged Markdown already exists")
            db.execute(
                "INSERT INTO rag_markdown_exports VALUES(?,?,?) "
                "ON CONFLICT(doc_id) DO UPDATE SET path=excluded.path,sha256=excluded.sha256",
                (row["doc_id"], relative, digest),
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_bytes() != data:
                _write_complete(target, data)
        except (OSError, ValueError) as error:
            errors.append(f"{row['path']}: Markdown 파일 저장 대기 ({type(error).__name__})")
    for row in db.execute("SELECT doc_id,path FROM rag_markdown_exports").fetchall():
        if row["doc_id"] in expected:
            continue
        try:
            target = _checked_path(root, row["path"])
            target.unlink(missing_ok=True)
            # Remove only our now-empty document directory; never recursively delete.
            if target.parent.exists() and not any(target.parent.iterdir()):
                target.parent.rmdir()
            db.execute("DELETE FROM rag_markdown_exports WHERE doc_id=?", (row["doc_id"],))
        except (OSError, ValueError) as error:
            errors.append("이전 Markdown 파일 정리 대기: " + type(error).__name__)

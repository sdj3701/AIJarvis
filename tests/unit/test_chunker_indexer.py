"""Tests for document chunking and indexing."""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from app.config.loader import load_policies, load_settings
from app.core.ids import SystemIdFactory
from app.memory.migrations import initialize_database
from app.rag.chunker import chunk_text
from app.rag.indexer import DocumentIndexer

pytestmark = pytest.mark.phase3
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 14, 0, tzinfo=KST)


@pytest.fixture
def indexer(tmp_path: Path) -> DocumentIndexer:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in ("settings", "tools", "privacy"):
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            config_dir / f"{name}.yaml",
        )
    settings_doc = yaml.safe_load((config_dir / "settings.yaml").read_text(encoding="utf-8"))
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True)
    settings_doc["paths"]["data_root"] = str(data_root)
    (config_dir / "settings.yaml").write_text(
        yaml.safe_dump(settings_doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    settings = load_settings(config_dir / "settings.yaml")
    policies = load_policies(
        config_dir / "tools.yaml",
        config_dir / "privacy.yaml",
        settings=settings,
    )
    docs_root = data_root / "docs"
    docs_root.mkdir(parents=True)
    shutil.copytree(REPOSITORY_ROOT / "tests" / "data" / "docs", docs_root, dirs_exist_ok=True)
    db = data_root / "memory" / "jarvis.sqlite3"
    initialize_database(db, created_at=NOW)
    return DocumentIndexer(
        database_path=db,
        docs_root=docs_root,
        settings=settings.rag,
        document_policy=policies.privacy.api_transmission.documents,
        ids=SystemIdFactory(),
    )


def test_chunk_overlap_produces_ordinals() -> None:
    text = "가" * 2500
    chunks = chunk_text(text, chunk_chars=1200, overlap_chars=150)
    assert len(chunks) >= 2
    assert chunks[0].ordinal == 0
    assert chunks[1].start_char == 1050


def test_index_and_search_public_doc(indexer: DocumentIndexer) -> None:
    report = indexer.sync(now=NOW)
    assert report.indexed + report.updated >= 1
    hits = indexer.search("Jarvis")
    assert hits
    assert any("guide.md" in hit.relative_path for hit in hits)


def test_reindex_same_file_does_not_duplicate_chunks(indexer: DocumentIndexer) -> None:
    indexer.sync(now=NOW)
    with closing(sqlite3.connect(indexer.database_path)) as connection:
        first = connection.execute("SELECT count(*) FROM doc_chunks").fetchone()[0]
    indexer.sync(now=NOW)
    with closing(sqlite3.connect(indexer.database_path)) as connection:
        second = connection.execute("SELECT count(*) FROM doc_chunks").fetchone()[0]
    assert first == second


def test_deleted_document_removed_from_fts(indexer: DocumentIndexer) -> None:
    indexer.sync(now=NOW)
    private = indexer.docs_root / "private" / "secret_notes.txt"
    private.unlink()
    indexer.sync(now=NOW)
    with closing(sqlite3.connect(indexer.database_path)) as connection:
        count = connection.execute(
            "SELECT count(*) FROM doc_chunks_fts WHERE doc_chunks_fts MATCH 'secret'"
        ).fetchone()[0]
    assert count == 0


def test_pdf_rejected_with_clear_message(indexer: DocumentIndexer, tmp_path: Path) -> None:
    pdf_path = indexer.docs_root / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    report = indexer.sync(now=NOW)
    assert report.errors
    assert any("PDF" in item for item in report.errors)

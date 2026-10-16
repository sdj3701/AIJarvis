"""PDF file projections must preserve the authoritative retrieval index."""

from dataclasses import replace

import pytest

from app.rag.generations import GenerationIndex
from app.rag.markdown_exports import export_root
from tests.helpers.pdf import text_pdf
from tests.unit.test_chunker_indexer import indexer  # noqa: F401
from tests.unit.test_semantic_memory import FakeEmbedder

pytestmark = pytest.mark.phase3


def prepare(ix, name="sample.pdf", text="Original PDF policy"):
    ix.semantic.embedder = FakeEmbedder()
    source = ix.docs_root / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(text_pdf([[text]]))
    assert not ix.sync().errors
    return source


def saved(ix):
    with ix._connection() as db:
        return [
            dict(r)
            for r in db.execute("""SELECT e.*,c.markdown,d.path AS source
            FROM rag_markdown_exports e JOIN rag_document_content c USING(doc_id)
            JOIN documents d USING(doc_id) ORDER BY d.path""")
        ]


def test_exact_utf8_idempotence_backfill_and_restore_without_reembedding(indexer, monkeypatch):  # noqa: F811
    source = prepare(indexer, "한글 문서.PDF")
    original = source.read_bytes()
    row = saved(indexer)[0]
    target = export_root(indexer.database_path) / row["path"]
    assert target.name == "한글 문서.md"
    assert target.read_bytes() == row["markdown"].encode("utf-8")
    generation = GenerationIndex(indexer).active()["id"]
    mtime = target.stat().st_mtime_ns

    def forbid(*args, **kwargs):
        pytest.fail("Unchanged PDF must not be parsed or embedded again")

    monkeypatch.setattr("app.rag.generations.parse_document", forbid)
    monkeypatch.setattr(indexer.semantic.embedder, "embed", forbid)
    assert not indexer.sync().errors
    assert target.stat().st_mtime_ns == mtime
    # Simulate a pre-export installation with persisted Markdown but no file/table row.
    target.unlink()
    with indexer._connection() as db, db:
        db.execute("DELETE FROM rag_markdown_exports")
    assert not replace(indexer).sync().errors
    assert target.read_bytes() == row["markdown"].encode("utf-8")
    target.write_bytes(b"Edited derived copy")
    assert not indexer.sync().errors
    assert target.read_bytes() == row["markdown"].encode("utf-8")
    assert GenerationIndex(indexer).active()["id"] == generation
    assert source.read_bytes() == original


def test_same_names_updates_deletions_and_unmanaged_files(indexer):  # noqa: F811
    first = prepare(indexer, "a/same.pdf", "First PDF body")
    second = prepare(indexer, "b/same.pdf", "Second PDF body")
    rows = saved(indexer)
    assert len(rows) == 2 and rows[0]["path"] != rows[1]["path"]
    root = export_root(indexer.database_path)
    unrelated = root / "my-notes.md"
    unrelated.write_text("User notes", encoding="utf-8")
    target = root / rows[0]["path"]
    first.write_bytes(text_pdf([["Updated PDF body"]]))
    assert not indexer.sync().errors
    assert "Updated PDF body" in target.read_text(encoding="utf-8")
    first.unlink()
    assert not indexer.sync().errors
    assert not target.exists()
    assert len(saved(indexer)) == 1
    assert second.exists() and unrelated.read_text(encoding="utf-8") == "User notes"


def test_atomic_failure_preserves_old_file_and_new_db_then_recovers(indexer, monkeypatch):  # noqa: F811
    import app.rag.markdown_exports as exports

    source = prepare(indexer)
    row = saved(indexer)[0]
    target = export_root(indexer.database_path) / row["path"]
    before = target.read_bytes()
    source.write_bytes(text_pdf([["Updated PDF policy"]]))
    original = exports.os.replace

    def denied(*args):
        raise PermissionError("simulated file lock")

    monkeypatch.setattr(exports.os, "replace", denied)
    report = indexer.sync()
    assert report.updated == 1 and any("Markdown" in e for e in report.errors)
    assert target.read_bytes() == before
    assert "Updated PDF policy" in saved(indexer)[0]["markdown"]
    assert not indexer.last_diagnostics["source_stale"]
    assert not list(target.parent.glob("*.tmp"))
    generation = GenerationIndex(indexer).active()["id"]
    monkeypatch.setattr(exports.os, "replace", original)
    assert not indexer.sync().errors
    assert target.read_bytes() == saved(indexer)[0]["markdown"].encode("utf-8")
    assert GenerationIndex(indexer).active()["id"] == generation


def test_failed_pdf_read_and_embedding_do_not_replace_export(indexer):  # noqa: F811
    source = prepare(indexer)
    row = saved(indexer)[0]
    target = export_root(indexer.database_path) / row["path"]
    before = target.read_bytes()
    source.write_bytes(b"%PDF broken")
    assert indexer.sync().errors
    assert target.read_bytes() == before
    source.write_bytes(text_pdf([["Not yet committed PDF"]]))
    indexer.semantic.embedder.offline = True
    assert indexer.sync().errors
    assert target.read_bytes() == before


def test_export_directory_never_reenters_index_with_broad_docs_root(indexer):  # noqa: F811
    ix = replace(indexer, docs_root=indexer.database_path.parent)
    prepare(ix)
    assert not ix.sync().errors
    with ix._connection() as db:
        assert [r[0] for r in db.execute("SELECT path FROM documents")] == ["sample.pdf"]
    assert len(saved(ix)) == 1


def test_unmanaged_conflict_is_not_overwritten_and_identical_orphan_can_recover(indexer):  # noqa: F811
    prepare(indexer)
    row = saved(indexer)[0]
    target = export_root(indexer.database_path) / row["path"]
    with indexer._connection() as db, db:
        db.execute("DELETE FROM rag_markdown_exports")
    target.write_bytes(b"Unmanaged different content")
    assert indexer.sync().errors
    assert target.read_bytes() == b"Unmanaged different content"
    # A crash after atomic replacement but before DB commit is safe to adopt.
    target.write_bytes(row["markdown"].encode("utf-8"))
    assert not indexer.sync().errors
    assert len(saved(indexer)) == 1


def test_pending_delete_retries_without_deleting_unmanaged_siblings(indexer, monkeypatch):  # noqa: F811
    from pathlib import Path

    source = prepare(indexer)
    row = saved(indexer)[0]
    target = export_root(indexer.database_path) / row["path"]
    sibling = target.with_name("user-notes.md")
    sibling.write_text("Keep", encoding="utf-8")
    source.unlink()
    original = Path.unlink

    def denied(path, *args, **kwargs):
        if path == target:
            raise PermissionError()
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied)
    assert indexer.sync().errors
    assert target.exists()
    monkeypatch.setattr(Path, "unlink", original)
    assert not indexer.sync().errors
    assert not target.exists() and sibling.exists()
    with indexer._connection() as db:
        assert not db.execute("SELECT 1 FROM rag_markdown_exports").fetchone()

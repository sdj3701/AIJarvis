import json
import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest

from app.rag.generations import GenerationIndex
from tests.unit.test_chunker_indexer import indexer  # noqa: F401
from tests.unit.test_semantic_memory import FakeEmbedder

pytestmark = pytest.mark.phase3


def setup(ix):
    ix.semantic.embedder = FakeEmbedder()
    assert not ix.sync().errors
    return GenerationIndex(ix)


def test_settings_alone_invalidate_chunks_and_preserve_source_ids(indexer):  # noqa: F811
    path = indexer.docs_root / "long.md"
    path.write_text("문맥 설명입니다. " * 100, encoding="utf-8")
    store = setup(indexer)
    first = store.active()["id"]
    changed = replace(
        indexer,
        settings=indexer.settings.model_copy(
            update={"chunk_chars": 200, "chunk_overlap_chars": 20}
        ),
    )
    report = changed.sync()
    assert report.updated > 0
    assert GenerationIndex(changed).active()["id"] != first
    with changed._connection() as db:
        assert db.execute("SELECT max(length(text)) FROM doc_chunks").fetchone()[0] <= 200
    assert changed.sync().updated == 0


def test_interrupted_prepare_preserves_active_then_recovers(indexer, monkeypatch):  # noqa: F811
    store = setup(indexer)
    before = store.active()["id"]
    path = indexer.docs_root / "travel.md"
    path.write_text("출장 식비 50000원", encoding="utf-8")
    publish = GenerationIndex.publish

    def crash(*args, **kwargs):
        raise RuntimeError("simulated crash after durable prepare")

    monkeypatch.setattr(GenerationIndex, "publish", crash)
    with pytest.raises(RuntimeError):
        indexer.sync()
    assert store.active()["id"] == before
    with indexer._connection() as db:
        assert not db.execute("SELECT 1 FROM documents WHERE path='travel.md'").fetchone()
    monkeypatch.setattr(GenerationIndex, "publish", publish)
    assert indexer.sync().indexed == 1
    assert store.active()["id"] != before


def test_embedding_failure_does_not_publish_half_generation(indexer):  # noqa: F811
    store = setup(indexer)
    before = store.active()["id"]
    (indexer.docs_root / "new.md").write_text("새 규정", encoding="utf-8")
    indexer.semantic.embedder.offline = True
    assert indexer.sync().errors
    assert store.active()["id"] == before
    assert indexer.last_diagnostics["source_stale"]


def test_active_model_mismatch_never_compares_different_vector_spaces(indexer):  # noqa: F811
    setup(indexer)
    indexer.semantic.embedder.identity = "test-model:changed"
    # A query before the next refresh may use lexical results, never old vectors.
    indexer.search("Jarvis")
    assert indexer.last_diagnostics["vector_candidates"] == 0
    assert indexer.last_diagnostics["embedding_error"]


def test_semantic_projection_failure_is_recovered_after_restart(indexer, monkeypatch):  # noqa: F811
    original = indexer.semantic.sync_documents
    indexer.semantic.embedder = FakeEmbedder()
    monkeypatch.setattr(
        indexer.semantic, "sync_documents", lambda rows: (_ for _ in ()).throw(OSError())
    )
    assert indexer.sync().errors
    store = GenerationIndex(indexer)
    generation = store.active()["id"]
    # Canonical text/vectors were published together despite projection failure.
    assert indexer.search("Jarvis")
    monkeypatch.setattr(indexer.semantic, "sync_documents", original)
    indexer.semantic.last_error = None  # a fresh process has no in-memory error flag
    indexer.semantic._retry_at = 0
    assert not indexer.sync().errors
    with indexer.semantic.connection() as db:
        assert db.execute("SELECT generation FROM document_projection").fetchone()[0] == generation


def test_refresh_and_delete_purge_retired_snapshots(indexer):  # noqa: F811
    ix = replace(indexer, settings=indexer.settings.model_copy(update={"refresh_interval_s": 0}))
    path = ix.docs_root / "travel.md"
    path.write_text("출장 식비는 30000원", encoding="utf-8")
    setup(ix)
    path.write_text("출장 식비는 50000원", encoding="utf-8")
    assert any("50000" in h.text for h in ix.search("출장 식비"))
    path.unlink()
    ix.search("출장 식비")
    with ix._connection() as db:
        assert db.execute("SELECT count(*) FROM rag_generations").fetchone()[0] == 1
        assert not db.execute("SELECT 1 FROM doc_chunks WHERE text LIKE '%50000%'").fetchone()


def test_explicit_rollback_restores_complete_previous_snapshot(indexer):  # noqa: F811
    store = setup(indexer)
    first = store.active()["id"]
    path = indexer.docs_root / "extra.md"
    path.write_text("추가 자료", encoding="utf-8")
    indexer.sync()
    current = store.active()["id"]
    store.publish(first, expected=current)
    assert store.active()["id"] == first
    with closing(sqlite3.connect(indexer.database_path)) as db:
        assert not db.execute("SELECT 1 FROM documents WHERE path='extra.md'").fetchone()


def test_chunk_policy_upgrade_reindexes_unchanged_files_once(indexer, monkeypatch):  # noqa: F811
    import app.rag.generations as generations

    current_policy = generations.DOCUMENT_CHUNK_POLICY
    monkeypatch.setattr(generations, "DOCUMENT_CHUNK_POLICY", "context-v1")
    store = setup(indexer)
    before = store.active()["id"]
    with indexer._connection() as db:
        ids = {r[0] for r in db.execute("SELECT chunk_id FROM doc_chunks")}
        doc_ids = {r[0] for r in db.execute("SELECT doc_id FROM documents")}
    monkeypatch.setattr(generations, "DOCUMENT_CHUNK_POLICY", current_policy)
    assert not indexer.sync().errors
    assert store.active()["id"] != before
    assert json.loads(store.active()["snapshot"])["policy"]["chunker"] == current_policy
    with indexer._connection() as db:
        assert not ids.intersection(r[0] for r in db.execute("SELECT chunk_id FROM doc_chunks"))
        assert doc_ids == {r[0] for r in db.execute("SELECT doc_id FROM documents")}
    upgraded = store.active()["id"]
    assert indexer.sync().updated == 0
    assert store.active()["id"] == upgraded


def test_search_does_not_chunk_or_index_question(indexer, monkeypatch):  # noqa: F811
    import app.rag.generations as generations

    store = setup(indexer)
    before = store.active()["snapshot"]
    seen = []
    model = indexer.semantic.embedder
    monkeypatch.setattr(
        model, "embed_query", lambda text: seen.append(text) or [0.0, 0.0, 1.0], raising=False
    )

    def forbid(*args, **kwargs):
        pytest.fail("Question entered document chunker")

    monkeypatch.setattr(generations, "document_chunks", forbid)
    question = "Jarvis 출장 규정 " * 100 + "임원은 제외해"
    indexer.search(question)
    assert seen == [question]
    assert store.active()["snapshot"] == before
    assert indexer.last_diagnostics["query_strategy"] == "whole-query"
    assert indexer.last_diagnostics["vector_candidates"] > 0


def test_pdf_roundtrip_cache_restart_failure_and_delete(indexer, monkeypatch):  # noqa: F811
    import app.rag.generations as generations
    from app.tools.impl.web_search import _doc_hit_dict
    from tests.helpers.pdf import text_pdf

    path = indexer.docs_root / "sample.pdf"
    path.write_bytes(text_pdf([["PDF policy important"], ["Second page policy"]]))
    store = setup(indexer)
    first = store.active()["id"]
    hits = [h for h in indexer.search("policy") if h.relative_path == "sample.pdf"]
    assert hits and hits[0].pages == (1, 2)
    assert _doc_hit_dict(hits[0])["pages"] == [1, 2]
    with indexer._connection() as db:
        saved = dict(
            db.execute(
                "SELECT * FROM rag_document_content WHERE markdown LIKE '%Second%'"
            ).fetchone()
        )
    assert saved["source_hash"]
    # Persisted Markdown is reused even after an indexer restart.
    original = generations.parse_document
    monkeypatch.setattr(generations, "parse_document", lambda *a, **k: pytest.fail("PDF reparsed"))
    restarted = replace(indexer)
    restarted.semantic.embedder = indexer.semantic.embedder
    assert not restarted.sync().errors
    assert GenerationIndex(restarted).active()["id"] == first
    monkeypatch.setattr(generations, "parse_document", original)
    path.write_bytes(b"%PDF corrupt")
    assert restarted.sync().errors
    assert restarted.last_diagnostics["source_stale"]
    assert store.active()["id"] == first
    with indexer._connection() as db:
        assert (
            db.execute(
                "SELECT markdown FROM rag_document_content WHERE doc_id=?", (saved["doc_id"],)
            ).fetchone()[0]
            == saved["markdown"]
        )
    path.unlink()
    assert not restarted.sync().errors
    with indexer._connection() as db:
        assert not db.execute(
            "SELECT 1 FROM rag_document_content WHERE doc_id=?", (saved["doc_id"],)
        ).fetchone()
        assert not db.execute(
            "SELECT 1 FROM rag_chunk_structure s LEFT JOIN doc_chunks c USING(chunk_id) "
            "WHERE c.chunk_id IS NULL"
        ).fetchone()


def test_pdf_can_be_disabled_in_settings(indexer):  # noqa: F811
    ix = replace(
        indexer,
        settings=indexer.settings.model_copy(update={"supported_extensions": [".md", ".txt"]}),
    )
    (ix.docs_root / "disabled.pdf").write_bytes(b"bad pdf")
    ix.semantic.embedder = FakeEmbedder()
    assert not ix.sync().errors

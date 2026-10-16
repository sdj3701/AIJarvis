"""Evaluation must reject invalid labels and keep operational data isolated."""
import sqlite3
from pathlib import Path

import pytest

from app.config.loader import load_config
from app.core.ids import SystemIdFactory
from app.memory.migrations import initialize_database
from app.rag.benchmark.answers import score_case
from app.rag.benchmark.models import EvaluationQuery
from app.rag.benchmark.service import snapshot_documents, validate_relevance
from app.rag.indexer import DocumentIndexer

pytestmark = pytest.mark.phase3


def test_snapshot_preserves_doc_ids_and_fts_but_excludes_other_tables(config_dir: Path):
    config = load_config(config_dir)
    root = config.settings.paths.data_root
    db_path = root / "memory" / "jarvis.sqlite3"
    initialize_database(db_path)
    docs = root / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("snapshot searchable document", encoding="utf-8")
    indexer = DocumentIndexer(db_path, docs, config.settings.rag,
                              config.policies.privacy.api_transmission.documents, SystemIdFactory())
    indexer.sync()
    connection = sqlite3.connect(db_path)
    with connection:
        connection.execute("CREATE TABLE private_probe(secret TEXT)")
        connection.execute("INSERT INTO private_probe VALUES ('do-not-copy')")
    connection.close()
    target = root / "isolated" / "documents.sqlite3"
    snapshot_documents(db_path, target)
    check = sqlite3.connect(target)
    try:
        assert check.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
        assert check.execute("SELECT count(*) FROM doc_chunks_fts WHERE doc_chunks_fts MATCH "
                             "'snapshot'").fetchone()[0] == 1
        assert not check.execute(
            "SELECT name FROM sqlite_master WHERE name='private_probe'"
        ).fetchall()
        doc_id = check.execute("SELECT doc_id FROM documents").fetchone()[0]
    finally:
        check.close()
    validate_relevance(target, (EvaluationQuery("q", "snapshot", "keyword", (doc_id,)),))
    with pytest.raises(ValueError, match="Unknown"):
        validate_relevance(target, (EvaluationQuery("q", "snapshot", "keyword", ("bad-id",)),))
    with pytest.raises(ValueError, match="separate"):
        snapshot_documents(db_path, target)


def test_abstention_cannot_score_as_a_correct_answer():
    case = {"expected_status": "근거 확인", "required_facts": [["3일"]], "source": "leave.md"}
    assert not score_case(case, "3일 근거 부족", "근거 부족", (), True)["passed"]
    assert score_case(case, "3 일 전 [1]\n\n근거:\nleave.md", "근거 확인",
                      ("leave.md#chunk=id",), True)["passed"]
    assert not score_case(case, "모름\n\n근거:\n3일", "근거 확인",
                          ("leave.md#chunk=id",), True)["passed"]

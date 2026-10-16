from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config.models import SemanticSettings
from app.rag.semantic import SemanticMemory

pytestmark = pytest.mark.phase3
NOW = datetime(2026, 10, 13, tzinfo=UTC)


class FakeEmbedder:
    identity = "test-model:revision-1"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.offline = False

    def embed(self, text: str) -> list[float]:
        if self.offline:
            raise OSError("offline")
        self.calls.append(text)
        if any(word in text for word in ("휴가", "쉬는", "연차")):
            return [1.0, 0.0, 0.0]
        if any(word in text for word in ("파스타", "스파게티")):
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


def memory(tmp_path: Path, embedder: FakeEmbedder) -> SemanticMemory:
    return SemanticMemory(tmp_path / "vectors.sqlite3", SemanticSettings(), embedder=embedder)


def test_document_vectors_persist_and_changes_remove_stale_hits(tmp_path: Path) -> None:
    embedder = FakeEmbedder()
    store = memory(tmp_path, embedder)
    store.sync_documents([{"chunk_id": "a", "doc_id": "doc", "text": "휴가 규정"}])
    assert store.document_ranking("쉬는 규정", limit=5) == ["a"]
    before = len(embedder.calls)
    reopened = memory(tmp_path, embedder)
    reopened.sync_documents([{"chunk_id": "a", "doc_id": "doc", "text": "휴가 규정"}])
    assert len(embedder.calls) == before
    reopened.sync_documents([{"chunk_id": "b", "doc_id": "doc", "text": "파스타 요리"}])
    assert reopened.document_ranking("쉬는 규정", limit=5) == []
    reopened.sync_documents([])
    assert reopened.stats()["documents"] == 0


def test_question_and_answer_are_searchable_across_restarts(tmp_path: Path) -> None:
    embedder = FakeEmbedder()
    store = memory(tmp_path, embedder)
    store.remember_turn(
        session_id="s1",
        turn_id="t1",
        question="좋아하는 음식",
        answer="파스타입니다.",
        created_at=NOW,
        sources=("guide.md",),
    )
    reopened = memory(tmp_path, embedder)
    hits = reopened.recall("스파게티", now=NOW)
    assert len(hits) == 1
    assert hits[0]["question"] == "좋아하는 음식"
    assert hits[0]["answer"] == "파스타입니다."
    assert hits[0]["sources"] == ["guide.md"]
    assert hits[0]["verified"] is False
    assert reopened.stats()["vectors"] == 2
    assert reopened.recall("스파게티", now=NOW, exclude_turn_id="t1") == []
    reopened.forget_turn("t1")
    assert reopened.recall("스파게티", now=NOW) == []
    assert reopened.stats()["vectors"] == 0


def test_outage_keeps_fts_and_pending_vectors_can_be_rebuilt(tmp_path: Path) -> None:
    embedder = FakeEmbedder()
    embedder.offline = True
    store = memory(tmp_path, embedder)
    store.remember_turn(
        session_id="s",
        turn_id="t",
        question="휴가 신청",
        answer="사흘 전에 신청합니다.",
        created_at=NOW,
    )
    assert store.recall("휴가", now=NOW)[0]["turn_id"] == "t"
    assert store.stats()["vectors"] == 0
    embedder.offline = False
    store.reindex()
    assert store.stats()["vectors"] == 2


def test_model_revision_and_dimension_never_mix(tmp_path: Path) -> None:
    embedder = FakeEmbedder()
    store = memory(tmp_path, embedder)
    docs = [{"chunk_id": "a", "doc_id": "doc", "text": "휴가"}]
    store.sync_documents(docs)
    embedder.identity = "test-model:revision-2"
    reopened = memory(tmp_path, embedder)
    reopened.sync_documents(docs)
    with sqlite3.connect(reopened.path) as db:
        models = db.execute("SELECT DISTINCT model FROM semantic_items").fetchall()
    assert models == [("test-model:revision-2",)]
    assert reopened.document_ranking("쉬는", limit=5) == ["a"]


def test_retention_and_long_answers(tmp_path: Path) -> None:
    store = memory(tmp_path, FakeEmbedder())
    answer = "파스타 " * 1000
    store.remember_turn(session_id="s", turn_id="t", question="음식", answer=answer, created_at=NOW)
    assert store.recall("스파게티", now=NOW)[0]["answer"] == answer
    assert store.stats()["vectors"] > 2
    assert store.recall("스파게티", now=NOW + timedelta(days=91)) == []
    assert store.stats()["vectors"] == 0


def test_vector_database_is_included_in_backup(tmp_path: Path) -> None:
    from scripts.backup import create_backup, restore_backup

    root = tmp_path / "data"
    store = SemanticMemory(
        root / "memory" / "semantic.sqlite3", SemanticSettings(), embedder=FakeEmbedder()
    )
    store.remember_turn(
        session_id="s", turn_id="t", question="취향", answer="파스타", created_at=NOW
    )
    archive = create_backup(root, tmp_path / "backups", password="test-only")
    target = tmp_path / "restored"
    restore_backup(archive, target, password="test-only")
    restored = SemanticMemory(
        target / "memory" / "semantic.sqlite3", SemanticSettings(), embedder=FakeEmbedder()
    )
    assert restored.recall("스파게티", now=NOW)[0]["answer"] == "파스타"


def test_same_id_changed_text_replaces_vector(tmp_path: Path) -> None:
    store = memory(tmp_path, FakeEmbedder())
    store.sync_documents([{"chunk_id": "a", "doc_id": "doc", "text": "휴가"}])
    store.sync_documents([{"chunk_id": "a", "doc_id": "doc", "text": "파스타"}])
    assert store.document_ranking("쉬는", limit=1) == []
    assert store.document_ranking("스파게티", limit=1) == ["a"]

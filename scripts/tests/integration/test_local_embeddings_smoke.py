"""Opt-in smoke test against the installed local Ollama embedding model."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.config.models import SemanticSettings
from app.rag.semantic import SemanticMemory

pytestmark = [pytest.mark.phase3, pytest.mark.allow_network]


def test_real_local_embeddings_survive_restart(tmp_path: Path) -> None:
    settings = SemanticSettings()
    store = SemanticMemory(tmp_path / "semantic.sqlite3", settings)
    store.sync_documents(
        [
            {
                "chunk_id": "leave",
                "doc_id": "hr",
                "text": "연차 휴가는 사용하기 사흘 전에 신청합니다.",
            },
            {
                "chunk_id": "food",
                "doc_id": "cooking",
                "text": "토마토 파스타는 면을 삶아 소스와 버무립니다.",
            },
        ]
    )
    assert store.last_error is None
    assert store.document_ranking("회사에서 쉬려면 언제 신청해야 하나요?", limit=2)[0] == "leave"
    now = datetime.now(UTC)
    store.remember_turn(
        session_id="smoke",
        turn_id="smoke-turn",
        question="내가 좋아하는 음식은?",
        answer="토마토 파스타입니다.",
        created_at=now,
        sources=("cooking",),
    )
    restarted = SemanticMemory(store.path, settings)
    hits = restarted.recall("내 스파게티 취향", now=now)
    assert hits and hits[0]["turn_id"] == "smoke-turn"
    with restarted.connection(vectors=True) as db:
        assert db.execute("SELECT DISTINCT dim FROM semantic_items").fetchall()[0][0] == 768
        assert db.execute("SELECT vec_version()").fetchone()[0]


def test_chat_runtime_persists_real_conversation_vectors(config_dir: Path) -> None:
    """Exercise the real runtime store instead of injecting a replacement indexer."""
    from app.llm.fake import FakeLLMClient
    from app.memory.migrations import initialize_database
    from app.orchestrator.loop import ChatOrchestrator
    from app.wiring import build

    llm = FakeLLMClient().reply("토마토 파스타를 좋아하시는군요.")
    runtime = build(config_dir, llm=llm)
    initialize_database(runtime.memory_db)
    chat = ChatOrchestrator(
        settings=runtime.config.settings, llm=llm, sessions=runtime.sessions,
        budget=runtime.budget, masker=runtime.masker, events=runtime.events,
        clock=runtime.clock, sleeper=runtime.sleeper, random=runtime.random,
        ids=runtime.ids, indexer=runtime.indexer,
    )
    chat.start()
    outcome = chat.handle_turn("나는 토마토 파스타를 좋아해")
    assert outcome.ok
    memory = runtime.indexer.semantic
    assert memory is not None
    assert memory.stats()["conversation_vectors"] == 2
    assert memory.stats()["pending_vectors"] == 0
    reopened = SemanticMemory(memory.path, memory.settings)
    hits = reopened.recall("내 스파게티 취향", now=datetime.now(UTC))
    assert hits[0]["turn_id"] == outcome.turn_id

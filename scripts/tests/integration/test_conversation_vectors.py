from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.rag.semantic import SemanticMemory
from app.wiring import Runtime, build
from tests.fakes.clock import FrozenClock
from tests.unit.test_semantic_memory import NOW, FakeEmbedder

pytestmark = pytest.mark.phase3


def make_chat(runtime: Runtime, llm: FakeLLMClient) -> ChatOrchestrator:
    semantic = SemanticMemory(
        runtime.memory_db.with_name("semantic.sqlite3"),
        runtime.config.settings.rag.semantic,
        embedder=FakeEmbedder(),
    )
    indexer = replace(runtime.indexer, semantic=semantic)
    return ChatOrchestrator(
        settings=runtime.config.settings,
        llm=llm,
        sessions=runtime.sessions,
        budget=runtime.budget,
        masker=runtime.masker,
        events=runtime.events,
        clock=runtime.clock,
        sleeper=runtime.sleeper,
        random=runtime.random,
        ids=runtime.ids,
        indexer=indexer,
    )


def test_completed_turn_is_recalled_after_restart_without_becoming_system_instruction(
    config_dir: Path,
) -> None:
    llm = FakeLLMClient().reply("파스타를 좋아하신다고 기억하겠습니다.")
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=llm)
    initialize_database(runtime.memory_db, created_at=NOW)
    first = make_chat(runtime, llm)
    first.start()
    outcome = first.handle_turn("나는 파스타를 좋아해")
    assert outcome.ok
    second_llm = FakeLLMClient().reply("파스타를 좋아하십니다.")
    second = make_chat(runtime, second_llm)
    second.start()
    assert second.handle_turn("스파게티 취향은?").ok
    messages = second_llm.calls[-1]
    recalled = [m for m in messages if 'source_kind="conversation"' in m.content]
    assert len(recalled) == 1
    assert recalled[0].role == "user"
    assert "나는 파스타를 좋아해" in recalled[0].content
    assert "미검증" in recalled[0].content
    assert "대화 2턴" in second.handle_turn("/recall status").text
    assert outcome.turn_id in second.handle_turn("/recall 스파게티").text
    second.handle_turn("/recall forget " + outcome.turn_id)
    assert "대화 1턴" in second.handle_turn("/recall status").text


def test_secret_turn_is_not_embedded(config_dir: Path) -> None:
    llm = FakeLLMClient().reply("확인했습니다.")
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=llm)
    initialize_database(runtime.memory_db, created_at=NOW)
    runtime.masker.register_secret("private-token-123456789")
    chat = make_chat(runtime, llm)
    chat.start()
    chat.handle_turn("private-token-123456789 보관")
    assert chat._semantic is not None
    assert chat._semantic.stats()["turns"] == 0


def test_model_outage_does_not_lose_answer_or_conversation(config_dir: Path) -> None:
    llm = FakeLLMClient().reply("휴가는 사흘 전에 신청합니다.")
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=llm)
    initialize_database(runtime.memory_db, created_at=NOW)
    chat = make_chat(runtime, llm)
    assert chat._semantic is not None
    chat._semantic.embedder.offline = True
    chat.start()
    assert chat.handle_turn("휴가 규정은?").ok
    assert "사흘" in chat.handle_turn("/recall 휴가").text
    assert chat._semantic.stats()["vectors"] == 0

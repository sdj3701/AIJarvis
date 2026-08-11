"""Integration tests for memory persistence across sessions."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.memory.commands import try_handle_memory_command
from app.memory.models import MemoryQuery
from tests.integration.test_chat_turn import EventingFakeLLM, _chat, _runtime

pytestmark = pytest.mark.phase2
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


def test_preference_applied_after_restart(config_dir: Path) -> None:
    llm = EventingFakeLLM().reply("기억했습니다").reply("짧게 답변")
    runtime = _runtime(config_dir, llm)
    chat = _chat(runtime, summarizer=runtime.summarizer)
    chat.start()
    ctx = chat.memory_command_context()
    assert ctx is not None
    result = try_handle_memory_command("기억해: 말투는 짧고 근거 포함", ctx)
    assert result is not None and result.ok is True
    chat.end(reason="bye")

    chat2 = _chat(runtime, summarizer=runtime.summarizer)
    chat2.start()
    outcome = chat2.handle_turn("내 말투 preference 알려줘")

    assert outcome.ok is True
    search = runtime.sessions.search(MemoryQuery(text="말투", now=NOW))
    assert any(item.record.key == "pref.answer_style" for item in search.matches)
    assert any(
        "confirmed_memory" in message.content
        for message in llm.calls[-1]
        if message.role == "system"
    )


def test_memory_eval_hits_expectations(config_dir: Path) -> None:
    llm = EventingFakeLLM()
    runtime = _runtime(config_dir, llm)
    chat = _chat(runtime)
    chat.start()
    ctx = chat.memory_command_context()
    assert ctx is not None
    samples = [
        ("기억해: 말투는 짧게", "pref.answer_style"),
        ("기억해: 언어는 한국어", "pref.language"),
        ("기억해: 노트 폴더는 D:\\notes", "env.notes_dir"),
    ]
    for text, key in samples:
        result = try_handle_memory_command(text, ctx)
        assert result is not None and result.ok is True
        stored = runtime.sessions.get_record(result.record_ids[0])
        assert stored is not None and stored.key == key

    eval_path = Path(__file__).resolve().parents[1] / "data" / "memory_eval.jsonl"
    lines = eval_path.read_text(encoding="utf-8").splitlines()
    hits = 0
    total = 0
    for line in lines:
        if not line.strip():
            continue
        total += 1
        item = json.loads(line)
        result = runtime.sessions.search(MemoryQuery(text=item["query"], now=NOW))
        found_keys = {scored.record.key for scored in result.matches if scored.record.key}
        if set(item["expect_keys"]).issubset(found_keys):
            hits += 1
    assert total > 0
    assert hits / total >= 0.9

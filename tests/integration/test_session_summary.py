"""Integration tests for session-end summarization."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import pytest

from app.cli import run_cli
from app.llm.fake import FakeLLMClient
from app.orchestrator.loop import ChatOrchestrator
from tests.integration.test_chat_turn import EventingFakeLLM, _chat, _runtime

pytestmark = pytest.mark.phase2
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)
TURN_ID = "turn_01KZQ6CQWDC6W068WDYMT2ZY4C"


def _summary_json(*, turn_id: str = TURN_ID) -> str:
    payload = {
        "schema_version": 1,
        "summary": "사용자가 답변 말투를 짧게 바꾸길 원함",
        "fact_candidates": [
            {
                "key": "pref.answer_style",
                "value": "짧고 근거 포함",
                "confidence": 0.8,
                "evidence_turn_ids": [turn_id],
            }
        ],
        "corrections": [],
        "tags": ["preference"],
    }
    return json.dumps(payload, ensure_ascii=False)


def test_bye_creates_summary_and_candidates(config_dir: Path) -> None:
    llm = EventingFakeLLM().reply("알겠습니다")
    runtime = _runtime(config_dir, llm)
    chat = _chat(runtime, summarizer=runtime.summarizer)
    chat.start()
    outcome = chat.handle_turn("앞으로 말투는 짧게")
    llm.reply(_summary_json(turn_id=outcome.turn_id))
    chat.end(reason="bye")

    summaries = runtime.sessions.list_records(kind="summary", status="confirmed")
    candidates = runtime.sessions.list_records(status="candidate")
    assert len(summaries) == 1
    assert len(candidates) == 1
    assert candidates[0].key == "pref.answer_style"


def test_cli_bye_runs_summarizer(config_dir: Path) -> None:
    llm = FakeLLMClient().reply("네").reply(_summary_json())
    runtime = _runtime(config_dir, llm)
    runtime.config.settings.memory.summarize_on_exit  # noqa: B018
    chat = ChatOrchestrator(
        settings=runtime.config.settings,
        llm=runtime.llm,
        sessions=runtime.sessions,
        budget=runtime.budget,
        masker=runtime.masker,
        events=runtime.events,
        clock=runtime.clock,
        sleeper=runtime.sleeper,
        random=runtime.random,
        ids=runtime.ids,
        summarizer=runtime.summarizer,
    )
    output = StringIO()
    exit_code = run_cli(
        input_stream=StringIO("안녕\n/bye\n"),
        output_stream=output,
        chat=chat,
    )

    assert exit_code == 0
    assert runtime.sessions.list_records(kind="summary")

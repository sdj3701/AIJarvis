"""Integration tests for the Phase 1 write-ahead chat flow."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.cli import run_cli
from app.llm.base import LLMResponse, LLMUsage, Message, ToolSpec
from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.wiring import Runtime, build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock

pytestmark = pytest.mark.phase1
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


class EventingFakeLLM(FakeLLMClient):
    def __init__(self, *, before_call: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.before_call = before_call

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        timeout_s: float,
        ctx: Any,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        prompt_version = "unversioned"
        if messages and messages[0].role == "system":
            first_line = messages[0].content.splitlines()[0]
            prompt_version = first_line.removeprefix("<!-- version: ").removesuffix(" -->")
        ctx.events.emit(
            "llm.request",
            {
                "model": self.model,
                "attempt": 1,
                "prompt_tokens_est": self.count_tokens(messages),
                "prompt_version": prompt_version,
                "tool_count": 0,
                "memory_record_ids": [],
            },
        )
        if self.before_call is not None:
            self.before_call()
        response = super().complete(
            messages=messages,
            tools=tools,
            timeout_s=timeout_s,
            ctx=ctx,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        ctx.events.emit(
            "llm.response",
            {
                "model": response.model,
                "finish_reason": response.finish_reason,
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "cost_usd": format(response.usage.cost_usd, "f"),
                "latency_ms": response.usage.latency_ms,
                "tool_call_names": [],
            },
        )
        return response


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    destination = tmp_path / "config"
    destination.mkdir()
    for name in ("settings", "tools", "privacy"):
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            destination / f"{name}.yaml",
        )
    root = tmp_path / "Jarvis"
    create_tree(root)
    settings_path = destination / "settings.yaml"
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    document["paths"]["data_root"] = str(root)
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return destination


def _runtime(config_dir: Path, llm: FakeLLMClient) -> Runtime:
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=llm)
    initialize_database(runtime.memory_db, created_at=NOW)
    return runtime


def _chat(
    runtime: Runtime,
    *,
    verify_model: Callable[[], object] | None = None,
) -> ChatOrchestrator:
    return ChatOrchestrator(
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
        verify_model=verify_model,
        metrics=runtime.metrics,
    )


def _events(runtime: Runtime) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    logs = runtime.config.settings.paths.data_root / "logs"
    for path in sorted(logs.glob("events-*.jsonl")):
        records.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return records


def test_user_raw_and_event_are_flushed_before_llm_and_ids_are_bound(config_dir: Path) -> None:
    observed: dict[str, bool] = {}
    llm = EventingFakeLLM().reply(
        "안녕하세요",
        usage=LLMUsage(12, 3, Decimal("0.00"), 25),
    )
    runtime = _runtime(config_dir, llm)
    chat = _chat(runtime)
    chat.start()

    def inspect_write_ahead_state() -> None:
        assert chat.session_id is not None
        raw = runtime.sessions.read_raw(chat.session_id)
        observed["raw_user"] = len(raw.records) == 1 and raw.records[0].role == "user"
        observed["user_event"] = "user.input" in [
            record["event_type"] for record in _events(runtime)
        ]

    llm.before_call = inspect_write_ahead_state
    outcome = chat.handle_turn("내 전화번호는 010-1234-5678입니다")

    assert outcome.ok is True
    assert outcome.text == "안녕하세요"
    assert observed == {"raw_user": True, "user_event": True}
    assert llm.calls[0][-1].content == "내 전화번호는 010-1234-5678입니다"
    assert chat.session_id is not None
    raw = runtime.sessions.read_raw(chat.session_id).records
    assert "010-1234-5678" not in raw[0].content
    assert [record.role for record in raw] == ["user", "assistant"]
    turn_events = [
        record
        for record in _events(runtime)
        if record["event_type"] in {"user.input", "llm.request", "llm.response"}
    ]
    assert [record["event_type"] for record in turn_events] == [
        "user.input",
        "llm.request",
        "llm.response",
    ]
    assert {record["request_id"] for record in turn_events} == {outcome.request_id}
    assert {record["turn_id"] for record in turn_events} == {outcome.turn_id}


def test_three_turns_keep_context_and_create_checkpoint(config_dir: Path) -> None:
    llm = EventingFakeLLM()
    for index in range(3):
        llm.reply(
            f"답변-{index}",
            usage=LLMUsage(10 + index, 2, Decimal("0.00"), 10),
        )
    runtime = _runtime(config_dir, llm)
    chat = _chat(runtime)

    for index in range(3):
        assert chat.handle_turn(f"질문-{index}").text == f"답변-{index}"

    assert [message.content for message in llm.calls[2][-5:]] == [
        "질문-0",
        "답변-0",
        "질문-1",
        "답변-1",
        "질문-2",
    ]
    assert chat.session_id is not None
    session = runtime.sessions.get_session(chat.session_id)
    assert session is not None
    assert session.turn_count == 3
    assert session.tokens_in == 33
    assert session.tokens_out == 6
    assert "session.checkpoint" in [record["event_type"] for record in _events(runtime)]
    assert runtime.metrics.p95_ms("llm.latency", window=200) == 10
    assert runtime.metrics.p95_ms("turn.latency", window=200) == 0


def test_clear_drops_prompt_history_but_keeps_raw_audit(config_dir: Path) -> None:
    llm = EventingFakeLLM().reply("첫 답").reply("둘째 답")
    runtime = _runtime(config_dir, llm)
    chat = _chat(runtime)
    chat.handle_turn("첫 질문")
    chat.clear()
    chat.handle_turn("둘째 질문")

    assert [message.role for message in llm.calls[1]] == ["system", "user"]
    assert llm.calls[1][-1].content == "둘째 질문"
    assert chat.session_id is not None
    assert [record.role for record in runtime.sessions.read_raw(chat.session_id).records] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_voice_channel_is_preserved_in_raw_context_and_metrics(config_dir: Path) -> None:
    llm = EventingFakeLLM().reply("음성 답변")
    runtime = _runtime(config_dir, llm)
    chat = _chat(runtime)

    outcome = chat.handle_turn("음성 질문", channel="voice")

    assert outcome.text == "음성 답변"
    assert chat.session_id is not None
    raw = runtime.sessions.read_raw(chat.session_id).records
    assert [record.channel for record in raw] == ["voice", "voice"]
    user_event = next(record for record in _events(runtime) if record["event_type"] == "user.input")
    assert user_event["payload"]["channel"] == "voice"


def test_llm_error_becomes_user_message_raw_note_and_error_event(config_dir: Path) -> None:
    from app.core.errors import LLMTimeout

    llm = EventingFakeLLM().raise_(LLMTimeout("로컬 모델 응답 시간이 초과되었습니다."))
    runtime = _runtime(config_dir, llm)
    chat = _chat(runtime)

    outcome = chat.handle_turn("실패 확인")

    assert outcome.ok is False
    assert "초과" in outcome.text
    assert chat.history == ()
    assert chat.session_id is not None
    raw = runtime.sessions.read_raw(chat.session_id).records
    assert [record.role for record in raw] == ["user", "system_note"]
    assert raw[-1].meta == {"status": "error", "error_type": "LLMTimeout"}
    assert "error" in [record["event_type"] for record in _events(runtime)]


def test_model_verifier_runs_once_after_input_is_saved(config_dir: Path) -> None:
    llm = EventingFakeLLM().reply("첫 답").reply("둘째 답")
    runtime = _runtime(config_dir, llm)
    calls: list[int] = []
    chat: ChatOrchestrator

    def verify() -> object:
        assert chat.session_id is not None
        assert runtime.sessions.read_raw(chat.session_id).records[-1].role == "user"
        calls.append(1)
        return object()

    chat = _chat(runtime, verify_model=verify)
    chat.handle_turn("첫 질문")
    chat.handle_turn("둘째 질문")

    assert calls == [1]


def test_end_closes_session_and_records_event(config_dir: Path) -> None:
    runtime = _runtime(config_dir, EventingFakeLLM())
    chat = _chat(runtime)
    session_id = chat.start()
    chat.end(reason="bye")

    session = runtime.sessions.get_session(session_id)
    assert session is not None and session.end_reason == "bye"
    assert chat.session_id is None
    assert _events(runtime)[-1]["event_type"] == "session.end"


def test_cli_dispatches_clear_budget_help_and_bye(config_dir: Path) -> None:
    llm = EventingFakeLLM().reply("첫 답").reply("둘째 답")
    runtime = _runtime(config_dir, llm)
    output = StringIO()

    exit_code = run_cli(
        input_stream=StringIO("/help\n첫 질문\n/clear\n/budget\n둘째 질문\n/bye\n"),
        output_stream=output,
        chat=_chat(runtime),
    )

    rendered = output.getvalue()
    assert exit_code == 0
    assert "/clear" in rendered
    assert "첫 답" in rendered and "둘째 답" in rendered
    assert "raw 기록은 유지" in rendered
    assert "오늘: $0.00/1.00" in rendered
    assert [message.role for message in llm.calls[1]] == ["system", "user"]

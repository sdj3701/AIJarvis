"""Integration tests for voice/text parity, safety boundaries, and privacy filtering."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.errors import ApprovalMismatch, JarvisError
from app.llm.base import LLMUsage
from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.safety.approval import ApprovalTicket
from app.voice.base import Transcript
from app.voice.controller import MISHEARD_TEXT, VoiceController
from app.wiring import Runtime, build
from scripts.bootstrap import create_tree
from tests.fakes.audio import FakeTTSEngine
from tests.fakes.clock import FrozenClock

pytestmark = pytest.mark.phase7

KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


class FakeListenerWithCommands:
    def __init__(
        self,
        commands: list[str | Transcript],
        *,
        barge_ins: list[bool] | None = None,
    ) -> None:
        self._commands = list(commands)
        self._barge_ins = list(barge_ins or [])
        self.wakes = 0

    def await_turn_start(self, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        from app.voice.controller import TurnStart

        self.wakes += 1
        return TurnStart("standalone", None)

    def listen_for_command(self, *args: Any, **kwargs: Any) -> Transcript:
        del args, kwargs
        if not self._commands:
            return Transcript("", "ko", 0, None)
        item = self._commands.pop(0)
        if isinstance(item, Transcript):
            return item
        return Transcript(item, "ko", 800, 0.9, -0.2, 0.01)

    def wait_for_barge_in(self, speech_done: Any, *, spoken_text: str = "") -> bool:
        del speech_done, spoken_text
        return self._barge_ins.pop(0) if self._barge_ins else False


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class SafeFakeLLMClient(FakeLLMClient):
    def complete(
        self,
        *,
        messages: Any,
        tools: Any = (),
        timeout_s: float,
        ctx: Any,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> Any:
        if not self.script:
            from app.llm.base import LLMResponse, LLMUsage
            summary_json = (
                '{"schema_version": 1, "summary": "대화 요약", '
                '"fact_candidates": [], "corrections": []}'
            )
            return LLMResponse(
                text=summary_json,
                tool_calls=(),
                usage=LLMUsage(0, 0, Decimal("0"), 0),
                model=self.model,
                finish_reason="stop",
            )
        return super().complete(
            messages=messages,
            tools=tools,
            timeout_s=timeout_s,
            ctx=ctx,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )


def _setup_test_app(
    config_dir: Path,
    *,
    replies: list[str] | None = None,
    tool_calls: list[tuple[str, dict[str, Any]]] | None = None,
) -> tuple[Runtime, ChatOrchestrator, FakeLLMClient]:
    settings_path = config_dir / "settings.yaml"
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    root = Path(document["paths"]["data_root"])
    create_tree(root)

    llm = SafeFakeLLMClient()
    if tool_calls:
        for name, args in tool_calls:
            llm.call_tool(name, **args)
    elif replies:
        for rep in replies:
            llm.reply(rep, usage=LLMUsage(10, 10, Decimal("0"), 1))
    else:
        llm.reply("확인했습니다.", usage=LLMUsage(10, 10, Decimal("0"), 1))

    clock = FrozenClock(NOW)
    runtime = build(config_dir, clock=clock, llm=llm)
    initialize_database(runtime.memory_db, created_at=NOW)

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
        metrics=runtime.metrics,
        summarizer=runtime.summarizer,
        indexer=runtime.indexer,
        research=runtime.research,
        tool_runner=runtime.tool_runner,
        safety_gate=runtime.safety_gate,
        approval_store=runtime.approval_store,
        audit_writer=runtime.audit_writer,
    )
    chat.start()
    return runtime, chat, llm


def test_voice_text_turn_parity(config_dir: Path) -> None:
    """Check that identical text received via voice and text yields equivalent outcomes."""
    runtime, chat, _ = _setup_test_app(
        config_dir,
        replies=["안녕하세요. 무엇을 도와드릴까요?", "안녕하세요. 무엇을 도와드릴까요?"],
    )

    text_outcome = chat.handle_turn("안녕하세요", channel="text")
    voice_outcome = chat.handle_turn("안녕하세요", channel="voice")

    assert text_outcome.ok is True
    assert voice_outcome.ok is True
    assert text_outcome.text == voice_outcome.text

    records = runtime.sessions.read_raw(chat.session_id).records
    channels = [r.channel for r in records if r.role == "user"]
    assert channels == ["text", "voice"]


def test_voice_controller_flow_parity(config_dir: Path) -> None:
    """Check end-to-end voice flow via VoiceController invoking ChatOrchestrator."""
    runtime, chat, _ = _setup_test_app(
        config_dir,
        replies=["메모장을 실행했습니다."],
    )

    listener = FakeListenerWithCommands(["메모장 열어줘"])
    tts = FakeTTSEngine()
    output = StringIO()

    controller = VoiceController(
        listener=listener,  # type: ignore[arg-type]
        tts=tts,
        chat=chat,
        masker=runtime.masker,
        acknowledgement="무엇을 도와드릴까요.",
        max_tts_chars=200,
        events=runtime.events,
        clock=runtime.clock,
        output_stream=output,
    )

    exit_code = controller.run(max_interactions=1)
    assert exit_code == 0
    assert listener.wakes == 1
    assert "무엇을 도와드릴까요." in tts.spoken
    assert any("시작했습니다" in s for s in tts.spoken)
    output_val = output.getvalue()
    assert "[Whisper 확정] 메모장 열어줘" in output_val or "인식: 메모장 열어줘" in output_val


def test_voice_high_risk_approval_blocked(config_dir: Path) -> None:
    """Verify that a high-risk tool approval is strictly blocked on the voice channel."""
    create_args = {
        "root": "notes",
        "relative_path": "test.md",
        "content": "내용",
        "overwrite": True,
    }
    runtime, chat, _llm = _setup_test_app(
        config_dir,
        tool_calls=[
            ("create_file", create_args),
            ("create_file", create_args),
        ],
    )

    # 1. Calling high risk tool directly on voice channel is immediately blocked
    voice_outcome = chat.handle_turn("파일 덮어써서 만들어줘", channel="voice")
    assert "음성 채널에서는 high 위험 작업을 실행할 수 없습니다" in voice_outcome.text
    assert voice_outcome.pending_approval is None

    # 2. Calling on text channel produces pending approval
    text_outcome = chat.handle_turn("파일 덮어써서 만들어줘", channel="text")
    assert text_outcome.pending_approval is not None
    verdict = text_outcome.pending_approval
    assert verdict.risk == "high"

    # 3. Attempting to grant approval for high risk on voice channel fails
    from dataclasses import replace

    voice_ctx = replace(chat.pending_context, channel="voice")  # type: ignore[arg-type]
    with pytest.raises(
        ApprovalMismatch,
        match="음성 채널에서는 high 위험 작업을 승인할 수 없습니다",
    ):
        runtime.approval_store.grant(
            verdict,
            ctx=voice_ctx,
            method="user_typed_phrase",
        )

    # 4. Text channel typed phrase approval succeeds
    ticket = runtime.approval_store.grant(
        verdict,
        ctx=chat.pending_context,  # type: ignore[arg-type]
        method="user_typed_phrase",
    )
    assert isinstance(ticket, ApprovalTicket)
    assert ticket.channel == "text"


def test_voice_sensitive_info_not_spoken(config_dir: Path) -> None:
    """Verify that secrets and PII_HIGH in response text are never spoken by TTS."""
    runtime, chat, _ = _setup_test_app(
        config_dir,
        replies=["API 키는 sk-ant-api03-1234567890abcdef1234567890abcdef 입니다."],
    )

    listener = FakeListenerWithCommands(["키 보여줘"])
    tts = FakeTTSEngine()
    output = StringIO()

    controller = VoiceController(
        listener=listener,  # type: ignore[arg-type]
        tts=tts,
        chat=chat,
        masker=runtime.masker,
        acknowledgement="무엇을 도와드릴까요.",
        max_tts_chars=200,
        events=runtime.events,
        clock=runtime.clock,
        output_stream=output,
    )

    controller.run(max_interactions=1)

    for spoken in tts.spoken:
        assert "sk-ant" not in spoken
        assert "1234567890" not in spoken

    assert any("민감한 내용이 포함되어 화면으로만 표시합니다" in s for s in tts.spoken)


def test_voice_barge_in_cancellation(config_dir: Path) -> None:
    """Verify that speaking can be interrupted and cancelled by wake detection."""
    runtime, chat, _ = _setup_test_app(
        config_dir,
        replies=["첫 번째 매우 긴 설명 답변입니다.", "두 번째 질문에 대한 답변입니다."],
    )

    listener = FakeListenerWithCommands(
        ["첫 질문", "두 번째 질문"],
        barge_ins=[True, False],
    )
    tts = FakeTTSEngine()
    output = StringIO()

    controller = VoiceController(
        listener=listener,  # type: ignore[arg-type]
        tts=tts,
        chat=chat,
        masker=runtime.masker,
        acknowledgement="무엇을 도와드릴까요.",
        max_tts_chars=200,
        events=runtime.events,
        clock=runtime.clock,
        output_stream=output,
    )

    controller.run(max_interactions=2)

    assert tts.cancelled >= 1
    assert "[답변 중단]" in output.getvalue()


def test_voice_quality_guard_rejects_garbage(config_dir: Path) -> None:
    """Verify that empty or low-confidence STT results do not reach Orchestrator."""
    runtime, chat, _ = _setup_test_app(config_dir, replies=["정상 답변"])

    # First command is empty transcript, second is valid command
    garbage_transcript = Transcript("", "ko", 100, None)
    valid_transcript = Transcript("정상 질문", "ko", 800, 0.9, -0.2, 0.01)

    listener = FakeListenerWithCommands([garbage_transcript, valid_transcript])
    tts = FakeTTSEngine()
    output = StringIO()

    controller = VoiceController(
        listener=listener,  # type: ignore[arg-type]
        tts=tts,
        chat=chat,
        masker=runtime.masker,
        acknowledgement="무엇을 도와드릴까요.",
        max_tts_chars=200,
        events=runtime.events,
        clock=runtime.clock,
        output_stream=output,
    )

    controller.run(max_interactions=1)

    assert MISHEARD_TEXT in tts.spoken
    assert "정상 답변" in tts.spoken


def test_voice_device_failure_isolated(config_dir: Path) -> None:
    """Verify that microphone stream failure does not crash or corrupt database state."""
    _runtime, chat, _ = _setup_test_app(config_dir)

    from app.voice.microphone import MicrophoneStream

    class BrokenBackend:
        def devices(self) -> Any:
            return ()

        def default_input(self) -> Any:
            return None

    mic = MicrophoneStream("none", backend=BrokenBackend())  # type: ignore[arg-type]
    with pytest.raises(JarvisError, match="설정한 마이크를 찾지 못했습니다"), mic:
        pass

    # Chat orchestrator still works reliably via text
    turn = chat.handle_turn("텍스트로 대화", channel="text")
    assert turn.ok is True

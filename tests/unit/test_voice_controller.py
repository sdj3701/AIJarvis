"""Tests for wake word to acknowledgement to voice chat orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from typing import Any

import pytest

from app.orchestrator.loop import TurnOutcome
from app.telemetry.masking import LogMasker
from app.voice.base import AudioFrame, Transcript
from app.voice.controller import LocalVoiceListener, VoiceController
from app.voice.stt import RecognitionUpdate
from tests.fakes.clock import FrozenClock

pytestmark = pytest.mark.phase7
NOW = datetime(2026, 8, 11, 21, 0, tzinfo=timezone(timedelta(hours=9)))


class FakeListener:
    def __init__(self, commands: list[str]) -> None:
        self.commands = commands
        self.wakes = 0

    def wait_for_wake(self) -> Transcript:
        self.wakes += 1
        return Transcript("자비스", "ko", 500, None)

    def listen_for_command(self) -> Transcript:
        return Transcript(self.commands.pop(0), "ko", 800, None)


class FakeTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.closed = False

    def speak(self, text: str, *, ctx: Any = None) -> None:
        del ctx
        self.spoken.append(text)

    def cancel(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class FakeChat:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[tuple[str, str]] = []
        self.ended = False

    def handle_turn(self, text: str, *, channel: str = "text") -> TurnOutcome:
        self.calls.append((text, channel))
        return TurnOutcome(True, self.answer, "req", "turn", 1, 1, Decimal("0"))

    def end(self, *, reason: str = "bye") -> None:
        del reason
        self.ended = True


class FakeEvents:
    def __init__(self) -> None:
        self.types: list[str] = []
        self.records: list[tuple[str, Any]] = []

    def emit(self, event_type: str, payload: Any) -> None:
        self.types.append(event_type)
        self.records.append((event_type, payload))


class FakeStreamingRecognizer:
    def feed(self, pcm: bytes) -> RecognitionUpdate:
        del pcm
        return RecognitionUpdate("자 비스", False)

    def finish(self) -> RecognitionUpdate:
        return RecognitionUpdate("", True)


class FakeStreamingSTT:
    def stream(self, *, phrases: Any = None) -> FakeStreamingRecognizer:
        del phrases
        return FakeStreamingRecognizer()


class FakeMicrophone:
    overflows = 0

    def __init__(self) -> None:
        self._sent = False

    def __enter__(self) -> FakeMicrophone:
        return self

    def next_frame(self, *, timeout_s: float = 0.5) -> AudioFrame | None:
        del timeout_s
        if self._sent:
            return None
        self._sent = True
        return AudioFrame(b"\x00\x00" * 160, 16_000)

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback


def _masker() -> LogMasker:
    from app.config.models import MaskPolicy

    return LogMasker([], MaskPolicy(replacement="[{label}]", keep_tail={}))


def test_wake_word_speaks_exact_acknowledgement_then_answer() -> None:
    listener = FakeListener(["대한민국 수도는 어디야"])
    tts = FakeTTS()
    chat = FakeChat("서울입니다.")
    events = FakeEvents()
    output = StringIO()
    controller = VoiceController(
        listener=listener,  # type: ignore[arg-type]
        tts=tts,
        chat=chat,  # type: ignore[arg-type]
        masker=_masker(),
        acknowledgement="무엇을 도와드릴까요.",
        max_tts_chars=400,
        events=events,
        clock=FrozenClock(NOW),
        output_stream=output,
    )

    assert controller.run(max_interactions=1) == 0

    assert tts.spoken == ["무엇을 도와드릴까요.", "서울입니다."]
    assert chat.calls == [("대한민국 수도는 어디야", "voice")]
    assert "인식: 대한민국 수도는 어디야" in output.getvalue()
    assert events.types == ["tts.result", "tts.result"]
    assert chat.ended is True and tts.closed is True


def test_spoken_exit_does_not_call_llm() -> None:
    tts = FakeTTS()
    chat = FakeChat("사용되면 안 됨")
    controller = VoiceController(
        listener=FakeListener(["종료"]),  # type: ignore[arg-type]
        tts=tts,
        chat=chat,  # type: ignore[arg-type]
        masker=_masker(),
        acknowledgement="무엇을 도와드릴까요.",
        max_tts_chars=400,
        events=FakeEvents(),
        clock=FrozenClock(NOW),
        output_stream=StringIO(),
    )

    controller.run()

    assert chat.calls == []
    assert tts.spoken == ["무엇을 도와드릴까요.", "안전하게 종료합니다."]


def test_voice_and_once_modes_are_mutually_exclusive() -> None:
    from app.__main__ import _parser

    with pytest.raises(SystemExit):
        _parser().parse_args(["--voice", "--once", "질문"])


def test_local_listener_accepts_spaced_wake_word_and_emits_mic_state() -> None:
    events = FakeEvents()
    output = StringIO()
    listener = LocalVoiceListener(
        stt=FakeStreamingSTT(),  # type: ignore[arg-type]
        microphone_factory=FakeMicrophone,  # type: ignore[arg-type]
        wake_word="자비스",
        command_timeout_s=15,
        device_label="테스트 마이크",
        events=events,
        clock=FrozenClock(NOW),
        output_stream=output,
    )

    transcript = listener.wait_for_wake()

    assert transcript.text == "자 비스"
    assert events.types == ["voice.recording", "voice.recording", "stt.result"]
    assert events.records[0][1]["state"] == "started"
    assert events.records[1][1]["state"] == "stopped"
    assert "[마이크 켜짐]" in output.getvalue()
    assert "[마이크 꺼짐]" in output.getvalue()

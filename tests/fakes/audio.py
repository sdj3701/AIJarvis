"""Deterministic audio fakes for offline Phase 7 tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any

from app.voice.base import AudioFrame, Transcript
from app.voice.microphone import InputDevice, OpenAudioStream


@dataclass
class FakeAudioStream:
    frames: list[AudioFrame] = field(default_factory=list)
    overflows: int = 0
    closed: bool = False
    entered: bool = False

    def __enter__(self) -> FakeAudioStream:
        self.entered = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def read(self, timeout_s: float | None = None) -> AudioFrame | None:
        del timeout_s
        if self.closed or not self.frames:
            return None
        return self.frames.pop(0)

    def close(self) -> None:
        self.closed = True


class FakeOpenStream:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeAudioBackend:
    devices_list: list[InputDevice] = field(default_factory=list)
    default_index: int | None = 0
    last_callback: Callable[[bytes, bool], None] | None = None
    stream: FakeOpenStream = field(default_factory=FakeOpenStream)

    def devices(self) -> Sequence[InputDevice]:
        if not self.devices_list:
            return (InputDevice(0, "Fake Microphone", 1),)
        return tuple(self.devices_list)

    def default_input(self) -> int | None:
        return self.default_index

    def open_input(
        self,
        *,
        device: int,
        sample_rate: int,
        block_size: int,
        callback: Callable[[bytes, bool], None],
    ) -> OpenAudioStream:
        del device, sample_rate, block_size
        self.last_callback = callback
        return self.stream


@dataclass
class FakeSTTEngine:
    responses: list[Transcript] = field(default_factory=list)
    calls: list[Sequence[AudioFrame]] = field(default_factory=list)
    default_text: str = "테스트 명령"

    def transcribe(self, frames: Sequence[AudioFrame]) -> Transcript:
        self.calls.append(list(frames))
        if self.responses:
            return self.responses.pop(0)
        return Transcript(self.default_text, "ko", len(frames) * 250, 0.9, -0.2, 0.01)


@dataclass
class FakeTTSEngine:
    spoken: list[str] = field(default_factory=list)
    cancelled: int = 0
    closed: bool = False
    on_speak: Callable[[str], None] | None = None

    def speak(self, text: str, *, ctx: Any = None) -> None:
        del ctx
        self.spoken.append(text)
        if self.on_speak is not None:
            self.on_speak(text)

    def cancel(self) -> None:
        self.cancelled += 1

    def close(self) -> None:
        self.closed = True

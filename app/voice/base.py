"""Engine-neutral voice contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.core.context import RequestContext


@dataclass(frozen=True, slots=True)
class AudioFrame:
    pcm: bytes
    sample_rate: int
    channels: int = 1
    sample_width_bytes: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.pcm, bytes):
            raise TypeError("AudioFrame.pcm must be bytes")
        if not isinstance(self.sample_rate, int) or self.sample_rate <= 0:
            raise ValueError("AudioFrame.sample_rate must be a positive integer")
        if self.channels != 1:
            raise ValueError("voice audio must be mono")
        if self.sample_width_bytes != 2:
            raise ValueError("voice audio must be 16-bit PCM")
        if len(self.pcm) % self.sample_width_bytes:
            raise ValueError("PCM byte length must align to the sample width")

    @property
    def duration_ms(self) -> int:
        samples = len(self.pcm) // self.sample_width_bytes
        return samples * 1000 // self.sample_rate


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: str
    duration_ms: int
    confidence: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("Transcript.text must be a string")
        if not self.language:
            raise ValueError("Transcript.language must not be empty")
        if self.duration_ms < 0:
            raise ValueError("Transcript.duration_ms must not be negative")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("Transcript.confidence must be between zero and one")


class STTEngine(Protocol):
    def transcribe(
        self,
        frames: Sequence[AudioFrame],
        *,
        ctx: RequestContext | None = None,
    ) -> Transcript: ...


class TTSEngine(Protocol):
    def speak(self, text: str, *, ctx: RequestContext | None = None) -> None: ...

    def cancel(self) -> None: ...

    def close(self) -> None: ...

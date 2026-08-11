"""Bounded, non-persistent PCM capture from a local microphone."""

from __future__ import annotations

import queue
from collections import deque
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol, cast

from app.core.errors import JarvisError
from app.voice.base import AudioFrame


@dataclass(frozen=True, slots=True)
class InputDevice:
    index: int
    name: str
    max_input_channels: int


class OpenAudioStream(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


class AudioBackend(Protocol):
    def devices(self) -> Sequence[InputDevice]: ...

    def default_input(self) -> int | None: ...

    def open_input(
        self,
        *,
        device: int,
        sample_rate: int,
        block_size: int,
        callback: Callable[[bytes, bool], None],
    ) -> OpenAudioStream: ...


def select_input_device(
    devices: Sequence[InputDevice], configured: str, *, default_input: int | None
) -> InputDevice:
    candidates = [
        device
        for device in devices
        if device.max_input_channels > 0
        and (configured == "default" or configured.casefold() in device.name.casefold())
    ]
    if default_input is not None:
        for device in candidates:
            if device.index == default_input:
                return device
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise JarvisError("설정한 마이크를 찾지 못했습니다.", {"device": configured})
    raise JarvisError(
        "같은 이름의 마이크가 여러 개입니다. 기본 입력 장치를 지정해 주세요.",
        {"device": configured, "matches": [item.index for item in candidates]},
    )


class SoundDeviceBackend:
    def __init__(self) -> None:
        try:
            self._sounddevice = import_module("sounddevice")
        except ImportError as error:
            raise JarvisError(
                "마이크 패키지가 없습니다. pip install -e .[voice]를 실행하세요."
            ) from error

    def devices(self) -> Sequence[InputDevice]:
        documents = cast(Sequence[dict[str, Any]], self._sounddevice.query_devices())
        return tuple(
            InputDevice(index, str(item["name"]), int(item["max_input_channels"]))
            for index, item in enumerate(documents)
        )

    def default_input(self) -> int | None:
        value = self._sounddevice.default.device[0]
        return int(value) if int(value) >= 0 else None

    def open_input(
        self,
        *,
        device: int,
        sample_rate: int,
        block_size: int,
        callback: Callable[[bytes, bool], None],
    ) -> OpenAudioStream:
        def on_audio(
            indata: Any,
            frames: int,
            time_info: Any,
            status: Any,
        ) -> None:
            del frames, time_info
            callback(bytes(indata), bool(status))

        return cast(
            OpenAudioStream,
            self._sounddevice.RawInputStream(
                samplerate=sample_rate,
                blocksize=block_size,
                device=device,
                dtype="int16",
                channels=1,
                callback=on_audio,
            ),
        )


class MicrophoneStream:
    """Keep only a short bounded in-memory queue; never write PCM to disk."""

    def __init__(
        self,
        device: str,
        *,
        sample_rate: int = 16_000,
        block_size: int = 4_000,
        max_blocks: int = 16,
        backend: AudioBackend | None = None,
    ) -> None:
        if sample_rate <= 0 or block_size <= 0 or max_blocks <= 0:
            raise ValueError("microphone sizes must be positive")
        self._configured_device = device
        self._sample_rate = sample_rate
        self._block_size = block_size
        self._backend = backend or SoundDeviceBackend()
        self._frames: queue.Queue[AudioFrame] = queue.Queue(maxsize=max_blocks)
        self._stream: OpenAudioStream | None = None
        self._overflows = 0

    @property
    def overflows(self) -> int:
        return self._overflows

    def __enter__(self) -> MicrophoneStream:
        selected = select_input_device(
            self._backend.devices(),
            self._configured_device,
            default_input=self._backend.default_input(),
        )
        try:
            self._stream = self._backend.open_input(
                device=selected.index,
                sample_rate=self._sample_rate,
                block_size=self._block_size,
                callback=self._on_audio,
            )
            self._stream.start()
        except Exception as error:
            self.close()
            raise JarvisError("마이크 입력을 시작하지 못했습니다.") from error
        return self

    def _on_audio(self, pcm: bytes, overflowed: bool) -> None:
        if overflowed:
            self._overflows += 1
        frame = AudioFrame(pcm, sample_rate=self._sample_rate)
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            self._overflows += 1
            with suppress(queue.Empty):
                self._frames.get_nowait()
            self._frames.put_nowait(frame)

    def next_frame(self, *, timeout_s: float = 0.5) -> AudioFrame | None:
        if timeout_s <= 0:
            raise ValueError("microphone timeout must be positive")
        try:
            return self._frames.get(timeout=timeout_s)
        except queue.Empty:
            return None

    def close(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback
        self.close()


@dataclass(frozen=True, slots=True)
class SpeechCapturePolicy:
    pre_roll_ms: int
    speech_threshold_dbfs: float
    trailing_silence_ms: int
    min_speech_ms: int
    max_duration_ms: int

    def __post_init__(self) -> None:
        if min(
            self.pre_roll_ms,
            self.trailing_silence_ms,
            self.min_speech_ms,
            self.max_duration_ms,
        ) <= 0:
            raise ValueError("speech capture durations must be positive")
        if not -96 <= self.speech_threshold_dbfs <= 0:
            raise ValueError("speech threshold must be between -96 and 0 dBFS")


class SpeechCapture:
    """Select one in-memory utterance using level and trailing-silence boundaries."""

    def __init__(self, policy: SpeechCapturePolicy) -> None:
        self._policy = policy
        self._pre_roll: deque[AudioFrame] = deque()
        self._pre_roll_duration_ms = 0
        self._frames: list[AudioFrame] = []
        self._input_duration_ms = 0
        self._speech_duration_ms = 0
        self._silence_duration_ms = 0
        self._speech_started = False
        self._finished = False
        self._finish_reason: str | None = None

    def feed(self, frame: AudioFrame) -> None:
        if self._finished:
            raise RuntimeError("speech capture is already finished")
        self._input_duration_ms += frame.duration_ms
        speech = frame.rms_dbfs >= self._policy.speech_threshold_dbfs
        if not self._speech_started:
            self._append_pre_roll(frame)
            if speech:
                self._speech_started = True
                self._frames.extend(self._pre_roll)
                self._pre_roll.clear()
                self._pre_roll_duration_ms = 0
                self._speech_duration_ms += frame.duration_ms
        else:
            self._frames.append(frame)
            if speech:
                self._speech_duration_ms += frame.duration_ms
                self._silence_duration_ms = 0
            else:
                self._silence_duration_ms += frame.duration_ms
                if self._silence_duration_ms >= self._policy.trailing_silence_ms:
                    self._finished = True
                    self._finish_reason = "trailing_silence"
        if not self._finished and self._input_duration_ms >= self._policy.max_duration_ms:
            self._finished = True
            self._finish_reason = "max_duration"

    def _append_pre_roll(self, frame: AudioFrame) -> None:
        self._pre_roll.append(frame)
        self._pre_roll_duration_ms += frame.duration_ms
        while (
            len(self._pre_roll) > 1
            and self._pre_roll_duration_ms - self._pre_roll[0].duration_ms
            >= self._policy.pre_roll_ms
        ):
            self._pre_roll_duration_ms -= self._pre_roll.popleft().duration_ms

    def expire(self) -> None:
        if not self._finished:
            self._finished = True
            self._finish_reason = "max_duration"

    def clear(self) -> None:
        """Discard buffered audio so a false wake candidate does not leak forward."""
        self._pre_roll.clear()
        self._pre_roll_duration_ms = 0
        self._frames.clear()
        self._input_duration_ms = 0
        self._speech_duration_ms = 0
        self._silence_duration_ms = 0
        self._speech_started = False
        self._finished = False
        self._finish_reason = None

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def speech_started(self) -> bool:
        return self._speech_started

    @property
    def finish_reason(self) -> str | None:
        return self._finish_reason

    @property
    def acceptable(self) -> bool:
        return self._speech_duration_ms >= self._policy.min_speech_ms

    @property
    def frames(self) -> tuple[AudioFrame, ...]:
        return tuple(self._frames)

    @property
    def input_duration_ms(self) -> int:
        return self._input_duration_ms

    @property
    def speech_duration_ms(self) -> int:
        return self._speech_duration_ms

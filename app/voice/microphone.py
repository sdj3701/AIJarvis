"""Bounded, non-persistent PCM capture from a local microphone."""

from __future__ import annotations

import queue
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

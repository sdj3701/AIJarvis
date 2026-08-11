"""Tests for local bounded microphone capture."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from app.voice.base import AudioFrame
from app.voice.microphone import (
    InputDevice,
    MicrophoneStream,
    SpeechCapture,
    SpeechCapturePolicy,
    select_input_device,
)

pytestmark = pytest.mark.phase7


class FakeStream:
    def __init__(self, callback: Callable[[bytes, bool], None]) -> None:
        self.callback = callback
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True


class FakeBackend:
    def __init__(self) -> None:
        self.stream: FakeStream | None = None

    def devices(self) -> Sequence[InputDevice]:
        return (
            InputDevice(1, "마이크(USB Condenser Microphone), MME", 1),
            InputDevice(10, "마이크(USB Condenser Microphone), DirectSound", 1),
        )

    def default_input(self) -> int | None:
        return 1

    def open_input(
        self,
        *,
        device: int,
        sample_rate: int,
        block_size: int,
        callback: Callable[[bytes, bool], None],
    ) -> FakeStream:
        assert (device, sample_rate, block_size) == (1, 16_000, 4_000)
        self.stream = FakeStream(callback)
        return self.stream


def test_device_substring_prefers_default_input() -> None:
    devices = FakeBackend().devices()

    selected = select_input_device(devices, "USB Condenser Microphone", default_input=1)

    assert selected.index == 1


def test_microphone_keeps_only_bounded_pcm_blocks() -> None:
    backend = FakeBackend()
    with MicrophoneStream("USB Condenser Microphone", max_blocks=1, backend=backend) as microphone:
        assert backend.stream is not None
        backend.stream.callback(b"\x00\x00" * 10, False)
        backend.stream.callback(b"\x01\x00" * 10, False)
        frame = microphone.next_frame(timeout_s=0.01)

    assert frame is not None and frame.pcm == b"\x01\x00" * 10
    assert microphone.overflows == 1
    assert backend.stream.closed is True


def _level_frame(amplitude: int, duration_ms: int = 250) -> AudioFrame:
    samples = 16_000 * duration_ms // 1000
    pcm = amplitude.to_bytes(2, "little", signed=True) * samples
    return AudioFrame(pcm, 16_000)


def test_speech_capture_keeps_pre_roll_and_stops_after_trailing_silence() -> None:
    capture = SpeechCapture(
        SpeechCapturePolicy(
            pre_roll_ms=500,
            speech_threshold_dbfs=-42,
            trailing_silence_ms=750,
            min_speech_ms=500,
            max_duration_ms=5_000,
        )
    )

    for amplitude in (0, 0, 4_000, 4_000, 0, 0, 0):
        capture.feed(_level_frame(amplitude))

    assert capture.finished is True
    assert capture.speech_started is True
    assert capture.acceptable is True
    assert capture.speech_duration_ms == 500
    assert sum(frame.duration_ms for frame in capture.frames) == 1_500


def test_speech_capture_times_out_without_sending_silence() -> None:
    capture = SpeechCapture(
        SpeechCapturePolicy(
            pre_roll_ms=500,
            speech_threshold_dbfs=-42,
            trailing_silence_ms=750,
            min_speech_ms=500,
            max_duration_ms=1_000,
        )
    )

    for _ in range(4):
        capture.feed(_level_frame(0))

    assert capture.finished is True
    assert capture.speech_started is False
    assert capture.acceptable is False
    assert capture.frames == ()


def test_speech_capture_can_expire_when_device_stops_delivering_frames() -> None:
    capture = SpeechCapture(
        SpeechCapturePolicy(500, -42, 750, 500, 1_000)
    )

    capture.expire()

    assert capture.finished is True
    assert capture.finish_reason == "max_duration"

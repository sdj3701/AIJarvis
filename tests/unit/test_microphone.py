"""Tests for local bounded microphone capture."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from app.voice.microphone import InputDevice, MicrophoneStream, select_input_device

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

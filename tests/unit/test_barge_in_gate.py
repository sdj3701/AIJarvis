"""Tests for the adaptive TTS-time microphone gate."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.voice.barge_in_gate import (
    BargeInGate,
    BargeInGatePolicy,
    WebRtcVoiceActivityDetector,
)
from app.voice.base import AudioFrame

pytestmark = pytest.mark.phase7


class SequenceVAD:
    def __init__(self, values: Sequence[bool]) -> None:
        self._values = iter(values)

    def is_voice(self, frame: AudioFrame) -> bool:
        del frame
        return next(self._values)


class CountingWebRtcVad:
    def __init__(self, results: Sequence[bool]) -> None:
        self._results = iter(results)
        self.calls: list[tuple[int, int]] = []

    def is_speech(self, pcm: bytes, sample_rate: int) -> bool:
        self.calls.append((len(pcm), sample_rate))
        return next(self._results)


def _frame(level: int, *, duration_ms: int = 250) -> AudioFrame:
    samples = 16_000 * duration_ms // 1_000
    pcm = level.to_bytes(2, "little", signed=True) * samples
    return AudioFrame(pcm, 16_000)


def _policy() -> BargeInGatePolicy:
    return BargeInGatePolicy(
        speech_threshold_dbfs=-32,
        min_onset_rise_db=8,
        baseline_window_ms=500,
        startup_guard_ms=500,
        recent_speech_ms=750,
        pre_roll_ms=500,
    )


def test_steady_loud_tts_echo_never_opens_gate() -> None:
    gate = BargeInGate(_policy(), SequenceVAD([True] * 5))

    decisions = [gate.feed(_frame(4_000)) for _ in range(5)]

    assert not any(item.onset or item.open for item in decisions)
    assert all(item.frames == () for item in decisions)


def test_voiced_level_onset_opens_with_bounded_pre_roll() -> None:
    gate = BargeInGate(_policy(), SequenceVAD([False, False, True]))
    quiet = _frame(300)
    speech = _frame(8_000)

    first = gate.feed(quiet)
    second = gate.feed(quiet)
    onset = gate.feed(speech)

    assert first.frames == () and second.frames == ()
    assert onset.onset is True and onset.open is True
    assert onset.voice is True
    assert onset.level_dbfs - onset.baseline_dbfs >= 8
    assert onset.frames == (quiet, quiet, speech)


def test_loud_non_voice_noise_does_not_open_gate() -> None:
    gate = BargeInGate(_policy(), SequenceVAD([False, False, False]))

    gate.feed(_frame(300))
    gate.feed(_frame(300))
    decision = gate.feed(_frame(10_000))

    assert decision.voice is False
    assert decision.onset is False
    assert decision.frames == ()


def test_gate_closure_requests_recognizer_reset() -> None:
    gate = BargeInGate(_policy(), SequenceVAD([False, False, True, True, True, True, True]))
    gate.feed(_frame(300))
    gate.feed(_frame(300))
    gate.feed(_frame(8_000))

    decisions = [gate.feed(_frame(8_000)) for _ in range(4)]

    assert decisions[-1].open is False
    assert decisions[-1].reset_recognizer is True


def test_webrtc_vad_splits_250ms_frame_into_supported_20ms_chunks() -> None:
    backend = CountingWebRtcVad([True] * 4 + [False] * 8)
    detector = WebRtcVoiceActivityDetector(
        frame_ms=20,
        min_voiced_ratio=0.3,
        vad_factory=lambda mode: backend,
    )

    assert detector.is_voice(_frame(4_000)) is True
    assert len(backend.calls) == 12
    assert set(backend.calls) == {(640, 16_000)}

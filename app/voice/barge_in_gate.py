"""Adaptive, local-only microphone gate for speech over playing TTS."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from statistics import median
from typing import Protocol, cast

from app.core.errors import JarvisError
from app.voice.base import AudioFrame


class VoiceActivityDetector(Protocol):
    def is_voice(self, frame: AudioFrame) -> bool: ...


class WebRtcVad(Protocol):
    def is_speech(self, pcm: bytes, sample_rate: int) -> bool: ...


VadFactory = Callable[[int], WebRtcVad]


def _create_webrtc_vad(mode: int) -> WebRtcVad:
    try:
        module = import_module("webrtcvad")
    except ImportError as error:
        raise JarvisError(
            "사람 음성 감지 패키지가 없습니다. pip install -e .[voice]를 실행하세요."
        ) from error
    return cast(WebRtcVad, module.Vad(mode))


class WebRtcVoiceActivityDetector:
    """Classify an AudioFrame from fixed-size WebRTC VAD subframes."""

    def __init__(
        self,
        *,
        mode: int = 2,
        frame_ms: int = 20,
        min_voiced_ratio: float = 0.3,
        vad_factory: VadFactory = _create_webrtc_vad,
    ) -> None:
        if mode not in {0, 1, 2, 3}:
            raise ValueError("WebRTC VAD mode must be between zero and three")
        if frame_ms not in {10, 20, 30}:
            raise ValueError("WebRTC VAD frame size must be 10, 20, or 30 ms")
        if not 0 < min_voiced_ratio <= 1:
            raise ValueError("minimum voiced ratio must be greater than zero and at most one")
        self._frame_ms = frame_ms
        self._min_voiced_ratio = min_voiced_ratio
        self._vad = vad_factory(mode)

    def is_voice(self, frame: AudioFrame) -> bool:
        bytes_per_subframe = (
            frame.sample_rate * self._frame_ms // 1_000 * frame.sample_width_bytes
        )
        subframes = len(frame.pcm) // bytes_per_subframe
        if subframes == 0:
            return False
        voiced = 0
        for index in range(subframes):
            start = index * bytes_per_subframe
            pcm = frame.pcm[start : start + bytes_per_subframe]
            if self._vad.is_speech(pcm, frame.sample_rate):
                voiced += 1
        return voiced / subframes >= self._min_voiced_ratio


@dataclass(frozen=True, slots=True)
class BargeInGatePolicy:
    speech_threshold_dbfs: float
    min_onset_rise_db: float
    baseline_window_ms: int
    startup_guard_ms: int
    recent_speech_ms: int
    pre_roll_ms: int

    def __post_init__(self) -> None:
        if not -96 <= self.speech_threshold_dbfs <= 0:
            raise ValueError("barge-in speech threshold must be between -96 and 0 dBFS")
        if not 0 <= self.min_onset_rise_db <= 96:
            raise ValueError("barge-in onset rise must be between zero and 96 dB")
        if min(
            self.baseline_window_ms,
            self.startup_guard_ms,
            self.recent_speech_ms,
            self.pre_roll_ms,
        ) <= 0:
            raise ValueError("barge-in gate durations must be positive")


@dataclass(frozen=True, slots=True)
class BargeInGateDecision:
    frames: tuple[AudioFrame, ...]
    level_dbfs: float
    baseline_dbfs: float
    voice: bool
    onset: bool
    open: bool
    reset_recognizer: bool


class BargeInGate:
    """Open briefly for a voiced level onset and keep all PCM in bounded memory."""

    def __init__(self, policy: BargeInGatePolicy, vad: VoiceActivityDetector) -> None:
        self._policy = policy
        self._vad = vad
        self._baseline: deque[tuple[float, int]] = deque()
        self._baseline_duration_ms = 0
        self._pre_roll: deque[AudioFrame] = deque()
        self._pre_roll_duration_ms = 0
        self._elapsed_ms = 0
        self._open_until_ms = 0
        self._open = False
        self._armed = True

    def feed(self, frame: AudioFrame) -> BargeInGateDecision:
        self._elapsed_ms += frame.duration_ms
        level_dbfs = frame.rms_dbfs
        baseline_dbfs = self._baseline_level()
        voice = self._vad.is_voice(frame)
        onset = (
            self._elapsed_ms > self._policy.startup_guard_ms
            and bool(self._baseline)
            and level_dbfs >= self._policy.speech_threshold_dbfs
            and level_dbfs - baseline_dbfs >= self._policy.min_onset_rise_db
            and voice
            and self._armed
        )
        was_open = self._open
        if onset:
            self._open_until_ms = self._elapsed_ms + self._policy.recent_speech_ms
            self._armed = False
        gate_open = self._elapsed_ms <= self._open_until_ms
        reset_recognizer = was_open and not gate_open

        if onset and not was_open:
            frames = (*self._pre_roll, frame)
            self._pre_roll.clear()
            self._pre_roll_duration_ms = 0
        elif gate_open:
            frames = (frame,)
        else:
            frames = ()
            self._append_pre_roll(frame)

        if not gate_open:
            self._append_baseline(level_dbfs, frame.duration_ms)
            if (
                level_dbfs < self._policy.speech_threshold_dbfs
                or level_dbfs - baseline_dbfs < self._policy.min_onset_rise_db
                or not voice
            ):
                self._armed = True
        self._open = gate_open
        return BargeInGateDecision(
            frames=frames,
            level_dbfs=level_dbfs,
            baseline_dbfs=baseline_dbfs,
            voice=voice,
            onset=onset,
            open=gate_open,
            reset_recognizer=reset_recognizer,
        )

    def _baseline_level(self) -> float:
        if not self._baseline:
            return -96.0
        return float(median(level for level, _ in self._baseline))

    def _append_baseline(self, level_dbfs: float, duration_ms: int) -> None:
        self._baseline.append((level_dbfs, duration_ms))
        self._baseline_duration_ms += duration_ms
        while (
            len(self._baseline) > 1
            and self._baseline_duration_ms - self._baseline[0][1]
            >= self._policy.baseline_window_ms
        ):
            _, removed_ms = self._baseline.popleft()
            self._baseline_duration_ms -= removed_ms

    def _append_pre_roll(self, frame: AudioFrame) -> None:
        self._pre_roll.append(frame)
        self._pre_roll_duration_ms += frame.duration_ms
        while (
            len(self._pre_roll) > 1
            and self._pre_roll_duration_ms - self._pre_roll[0].duration_ms
            >= self._policy.pre_roll_ms
        ):
            self._pre_roll_duration_ms -= self._pre_roll.popleft().duration_ms

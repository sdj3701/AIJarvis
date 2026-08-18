"""Soft local source filter: music rejection and optional owner speaker match."""

from __future__ import annotations

import array
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.voice.base import AudioFrame

SourceLabel = Literal["music", "other_speaker", "owner", "unknown"]
SourcePath = Literal["wake", "barge_in", "command"]


@dataclass(frozen=True, slots=True)
class SourceFilterPolicy:
    enabled: bool
    music_enabled: bool
    speaker_enabled: bool
    music_reject_threshold: float
    speech_margin: float
    owner_accept_threshold: float
    other_reject_threshold: float
    analysis_window_ms: int

    def __post_init__(self) -> None:
        if not 0 <= self.music_reject_threshold <= 1:
            raise ValueError("music_reject_threshold must be between 0 and 1")
        if not 0 <= self.speech_margin <= 1:
            raise ValueError("speech_margin must be between 0 and 1")
        if not 0 <= self.owner_accept_threshold <= 1:
            raise ValueError("owner_accept_threshold must be between 0 and 1")
        if not 0 <= self.other_reject_threshold <= 1:
            raise ValueError("other_reject_threshold must be between 0 and 1")
        if self.owner_accept_threshold <= self.other_reject_threshold:
            raise ValueError("owner_accept_threshold must exceed other_reject_threshold")
        if self.analysis_window_ms <= 0:
            raise ValueError("analysis_window_ms must be positive")


@dataclass(frozen=True, slots=True)
class MusicSpeechScores:
    music: float
    speech: float
    singing: float = 0.0


@dataclass(frozen=True, slots=True)
class SourceDecision:
    label: SourceLabel
    accept: bool
    reason: str
    music_score: float | None = None
    speaker_score: float | None = None


class SpeechMusicClassifier(Protocol):
    def score(self, frames: Sequence[AudioFrame]) -> MusicSpeechScores: ...


class SpeakerEmbedder(Protocol):
    def embed(self, frames: Sequence[AudioFrame]) -> tuple[float, ...]: ...


def concat_pcm(frames: Sequence[AudioFrame]) -> tuple[bytes, int]:
    if not frames:
        raise ValueError("frames must not be empty")
    sample_rate = frames[0].sample_rate
    for frame in frames:
        if frame.sample_rate != sample_rate:
            raise ValueError("all frames must share the same sample rate")
    return b"".join(frame.pcm for frame in frames), sample_rate


def window_frames(
    frames: Sequence[AudioFrame], *, window_ms: int
) -> tuple[AudioFrame, ...]:
    if window_ms <= 0:
        raise ValueError("window_ms must be positive")
    if not frames:
        return ()
    total = 0
    selected: list[AudioFrame] = []
    for frame in reversed(frames):
        selected.append(frame)
        total += frame.duration_ms
        if total >= window_ms:
            break
    selected.reverse()
    return tuple(selected)


def voiced_frames(
    frames: Sequence[AudioFrame],
    *,
    threshold_dbfs: float,
    min_ms: int,
) -> tuple[AudioFrame, ...]:
    """Keep frames above a level floor; fall back to the full window if too short."""
    voiced = tuple(frame for frame in frames if frame.rms_dbfs >= threshold_dbfs)
    voiced_ms = sum(frame.duration_ms for frame in voiced)
    if voiced and voiced_ms >= min_ms:
        return voiced
    return tuple(frames)


def l2_normalize(vector: Sequence[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        raise ValueError("embedding norm must be positive")
    return tuple(value / norm for value in vector)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions must match")
    if not left:
        raise ValueError("embeddings must not be empty")
    return sum(a * b for a, b in zip(left, right, strict=True))


def pcm16_mono_samples(pcm: bytes) -> array.array[int]:
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


class SpectralSpeechMusicClassifier:
    """Heuristic music/speech scorer using tonality and zero-crossing rate."""

    def score(self, frames: Sequence[AudioFrame]) -> MusicSpeechScores:
        if not frames:
            return MusicSpeechScores(music=0.0, speech=0.0, singing=0.0)
        pcm, sample_rate = concat_pcm(frames)
        del sample_rate
        samples = pcm16_mono_samples(pcm)
        if len(samples) < 256:
            return MusicSpeechScores(music=0.0, speech=0.0, singing=0.0)

        zcr = _zero_crossing_rate(samples)
        tonality = _tonality_score(samples)
        energy_cv = _energy_coefficient_of_variation(samples)

        # Sustained tones (music): high tonality, lower ZCR, steadier energy.
        music = _clamp01(0.65 * tonality + 0.35 * (1.0 - _clamp01(zcr / 0.25)))
        music = _clamp01(music * (1.0 - 0.35 * _clamp01(energy_cv / 1.2)))
        singing = _clamp01(music * 0.9)
        # Speech: higher ZCR and more energy variation.
        speech = _clamp01(0.55 * _clamp01(zcr / 0.18) + 0.45 * _clamp01(energy_cv / 0.9))
        if speech > music:
            music = _clamp01(music * 0.65)
            singing = _clamp01(singing * 0.65)
        return MusicSpeechScores(music=music, speech=speech, singing=singing)


class OnnxYamNetSpeechMusicClassifier:
    """Optional AudioSet-tag ONNX scorer when a local YAMNet file is present."""

    def __init__(self, model_path: Path) -> None:
        self._model_path = model_path
        self._session: object | None = None
        self._failed = False

    def score(self, frames: Sequence[AudioFrame]) -> MusicSpeechScores:
        if self._failed:
            raise RuntimeError("YAMNet ONNX session previously failed to load")
        session = self._ensure_session()
        pcm, sample_rate = concat_pcm(frames)
        waveform = _pcm_to_float_mono(pcm)
        if sample_rate != 16_000:
            raise ValueError("YAMNet classifier expects 16 kHz PCM")
        # Generic ONNX contracts differ by export; treat first output as class scores.
        outputs = session.run(None, {session.get_inputs()[0].name: waveform})  # type: ignore[attr-defined]
        scores = outputs[0]
        flat = _flatten_scores(scores)
        # AudioSet indices commonly used in YAMNet class map (Speech=0, Music=137, Singing=27)
        speech = _index_or_zero(flat, 0)
        singing = _index_or_zero(flat, 27)
        music = _index_or_zero(flat, 137)
        return MusicSpeechScores(music=music, speech=speech, singing=singing)

    def _ensure_session(self) -> object:
        if self._session is not None:
            return self._session
        try:
            from importlib import import_module

            ort = import_module("onnxruntime")
            self._session = ort.InferenceSession(
                str(self._model_path),
                providers=["CPUExecutionProvider"],
            )
        except Exception as error:
            self._failed = True
            raise RuntimeError(f"failed to load YAMNet ONNX: {error}") from error
        return self._session


class SpeakerSoftMatcher:
    def __init__(
        self,
        owner_embedding: Sequence[float],
        *,
        owner_accept_threshold: float,
        other_reject_threshold: float,
    ) -> None:
        if owner_accept_threshold <= other_reject_threshold:
            raise ValueError("owner_accept_threshold must exceed other_reject_threshold")
        self._owner = l2_normalize(owner_embedding)
        self._owner_accept_threshold = owner_accept_threshold
        self._other_reject_threshold = other_reject_threshold

    @property
    def owner_embedding(self) -> tuple[float, ...]:
        return self._owner

    def match(self, embedding: Sequence[float]) -> tuple[SourceLabel, float]:
        score = cosine_similarity(self._owner, l2_normalize(embedding))
        if score >= self._owner_accept_threshold:
            return "owner", score
        if score <= self._other_reject_threshold:
            return "other_speaker", score
        return "unknown", score


class SourceFilter:
    """Compose music and soft speaker gates with fail-open behavior."""

    def __init__(
        self,
        policy: SourceFilterPolicy,
        *,
        music_classifier: SpeechMusicClassifier | None = None,
        speaker_embedder: SpeakerEmbedder | None = None,
        speaker_matcher: SpeakerSoftMatcher | None = None,
    ) -> None:
        self._policy = policy
        self._music = music_classifier
        self._embedder = speaker_embedder
        self._matcher = speaker_matcher
        self._music_warning_pending = False
        self._speaker_warning_pending = False
        self._music_warning_emitted = False
        self._speaker_warning_emitted = False

    @property
    def policy(self) -> SourceFilterPolicy:
        return self._policy

    def classify(
        self,
        frames: Sequence[AudioFrame],
        *,
        path: SourcePath,
    ) -> SourceDecision:
        del path  # used by callers for telemetry; decision itself is path-agnostic
        if not self._policy.enabled:
            return SourceDecision("unknown", True, "filter_disabled")

        window = window_frames(frames, window_ms=self._policy.analysis_window_ms)
        if not window:
            return SourceDecision("unknown", True, "empty_window")

        music_score: float | None = None
        music_failed = False
        if self._policy.music_enabled and self._music is not None:
            try:
                scores = self._music.score(window)
                music_like = max(scores.music, scores.singing)
                if (
                    music_like >= self._policy.music_reject_threshold
                    and scores.speech < music_like - self._policy.speech_margin
                ):
                    return SourceDecision(
                        "music",
                        False,
                        "music_or_singing",
                        music_score=music_like,
                    )
                music_score = music_like
            except Exception:
                music_failed = True
                if not self._music_warning_emitted:
                    self._music_warning_pending = True
                    self._music_warning_emitted = True

        if (
            self._policy.speaker_enabled
            and self._embedder is not None
            and self._matcher is not None
        ):
            try:
                # Prefer louder frames so trailing silence does not dilute ECAPA.
                speaker_window = voiced_frames(
                    window,
                    threshold_dbfs=-42.0,
                    min_ms=300,
                )
                embedding = self._embedder.embed(speaker_window)
                label, speaker_score = self._matcher.match(embedding)
            except Exception:
                if not self._speaker_warning_emitted:
                    self._speaker_warning_pending = True
                    self._speaker_warning_emitted = True
                return SourceDecision(
                    "unknown",
                    True,
                    "speaker_matcher_failed",
                    music_score=music_score,
                )
            accept = label != "other_speaker"
            return SourceDecision(
                label,
                accept,
                "speaker_soft",
                music_score=music_score,
                speaker_score=speaker_score,
            )

        reason = "music_classifier_failed" if music_failed else "music_passed_or_skipped"
        return SourceDecision(
            "unknown",
            True,
            reason,
            music_score=music_score,
        )

    def consume_music_warning(self) -> bool:
        if self._music_warning_pending:
            self._music_warning_pending = False
            return True
        return False

    def consume_speaker_warning(self) -> bool:
        if self._speaker_warning_pending:
            self._speaker_warning_pending = False
            return True
        return False


def build_music_classifier(
    *,
    yamnet_model_path: Path | None,
) -> SpeechMusicClassifier:
    if yamnet_model_path is not None and yamnet_model_path.is_file():
        try:
            classifier = OnnxYamNetSpeechMusicClassifier(yamnet_model_path)
            # Probe load once so callers get spectral fallback on broken exports.
            classifier._ensure_session()
            return classifier
        except Exception:
            pass
    return SpectralSpeechMusicClassifier()


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _zero_crossing_rate(samples: array.array[int]) -> float:
    if len(samples) < 2:
        return 0.0
    crossings = 0
    previous = samples[0]
    for sample in samples[1:]:
        if (previous >= 0 > sample) or (previous < 0 <= sample):
            crossings += 1
        previous = sample
    return crossings / (len(samples) - 1)


def _tonality_score(samples: array.array[int]) -> float:
    """Estimate periodicity via a coarse autocorrelation peak ratio."""
    # Downsample for speed while keeping pitch-range structure.
    step = max(1, len(samples) // 2_000)
    series = samples[::step]
    if len(series) < 64:
        return 0.0
    mean = sum(series) / len(series)
    centered = [value - mean for value in series]
    energy = sum(value * value for value in centered)
    if energy <= 0:
        return 0.0
    min_lag = max(2, len(centered) // 40)
    max_lag = max(min_lag + 1, len(centered) // 4)
    best = 0.0
    for lag in range(min_lag, max_lag):
        corr = 0.0
        limit = len(centered) - lag
        for index in range(limit):
            corr += centered[index] * centered[index + lag]
        best = max(best, corr / energy)
    return _clamp01(best)


def _energy_coefficient_of_variation(samples: array.array[int]) -> float:
    window = 320  # 20 ms at 16 kHz
    if len(samples) < window * 2:
        return 0.0
    energies: list[float] = []
    for start in range(0, len(samples) - window + 1, window):
        chunk = samples[start : start + window]
        energies.append(sum(sample * sample for sample in chunk) / window)
    mean = sum(energies) / len(energies)
    if mean <= 0:
        return 0.0
    variance = sum((value - mean) ** 2 for value in energies) / len(energies)
    return math.sqrt(variance) / mean


def _pcm_to_float_mono(pcm: bytes) -> list[float]:
    samples = pcm16_mono_samples(pcm)
    return [sample / 32_768.0 for sample in samples]


def _flatten_scores(scores: object) -> list[float]:
    if isinstance(scores, (list, tuple)):
        if scores and isinstance(scores[0], (list, tuple)):
            return [float(item) for row in scores for item in row]
        return [float(item) for item in scores]
    # numpy-like
    tolist = getattr(scores, "tolist", None)
    if callable(tolist):
        return _flatten_scores(tolist())
    raise TypeError("unsupported ONNX score output")


def _index_or_zero(values: Sequence[float], index: int) -> float:
    if 0 <= index < len(values):
        return _clamp01(float(values[index]))
    return 0.0

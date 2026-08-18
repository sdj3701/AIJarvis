"""Synthetic audio and fake classifiers for source-filter tests."""

from __future__ import annotations

import math
from collections.abc import Sequence

from app.voice.base import AudioFrame
from app.voice.source_filter import MusicSpeechScores


def sine_frames(
    *,
    frequency_hz: float = 440.0,
    duration_ms: int = 1_200,
    sample_rate: int = 16_000,
    amplitude: int = 8_000,
    frame_ms: int = 250,
) -> tuple[AudioFrame, ...]:
    frames: list[AudioFrame] = []
    total_samples = sample_rate * duration_ms // 1_000
    frame_samples = sample_rate * frame_ms // 1_000
    for start in range(0, total_samples, frame_samples):
        size = min(frame_samples, total_samples - start)
        pcm = bytearray()
        for index in range(size):
            sample = int(
                amplitude * math.sin(2 * math.pi * frequency_hz * (start + index) / sample_rate)
            )
            pcm.extend(sample.to_bytes(2, "little", signed=True))
        frames.append(AudioFrame(bytes(pcm), sample_rate))
    return tuple(frames)


def noise_frames(
    *,
    duration_ms: int = 1_200,
    sample_rate: int = 16_000,
    amplitude: int = 6_000,
    frame_ms: int = 250,
    seed: int = 1,
) -> tuple[AudioFrame, ...]:
    """Generate high-ZCR noise that looks more speech-like to the spectral scorer."""
    frames: list[AudioFrame] = []
    total_samples = sample_rate * duration_ms // 1_000
    frame_samples = sample_rate * frame_ms // 1_000
    state = seed
    for start in range(0, total_samples, frame_samples):
        size = min(frame_samples, total_samples - start)
        pcm = bytearray()
        for _ in range(size):
            # xorshift-ish deterministic noise
            state ^= (state << 13) & 0xFFFFFFFF
            state ^= (state >> 17) & 0xFFFFFFFF
            state ^= (state << 5) & 0xFFFFFFFF
            sample = int(((state & 0xFFFF) / 0xFFFF) * 2 * amplitude - amplitude)
            # Amplify zero crossings with square-ish polarity flips.
            if state & 1:
                sample = -sample
            pcm.extend(max(-32_767, min(32_767, sample)).to_bytes(2, "little", signed=True))
        frames.append(AudioFrame(bytes(pcm), sample_rate))
    return tuple(frames)


class FixedMusicClassifier:
    def __init__(self, scores: MusicSpeechScores) -> None:
        self.scores = scores
        self.calls = 0

    def score(self, frames: Sequence[AudioFrame]) -> MusicSpeechScores:
        del frames
        self.calls += 1
        return self.scores


class ExplodingMusicClassifier:
    def score(self, frames: Sequence[AudioFrame]) -> MusicSpeechScores:
        del frames
        raise RuntimeError("music model missing")


class FixedSpeakerEmbedder:
    def __init__(self, embedding: Sequence[float]) -> None:
        self.embedding = tuple(float(value) for value in embedding)
        self.calls = 0

    def embed(self, frames: Sequence[AudioFrame]) -> tuple[float, ...]:
        del frames
        self.calls += 1
        return self.embedding


class SequenceSpeakerEmbedder:
    def __init__(self, embeddings: Sequence[Sequence[float]]) -> None:
        self._embeddings = [tuple(float(value) for value in item) for item in embeddings]
        self.calls = 0

    def embed(self, frames: Sequence[AudioFrame]) -> tuple[float, ...]:
        del frames
        if self.calls >= len(self._embeddings):
            raise RuntimeError("no embeddings left")
        embedding = self._embeddings[self.calls]
        self.calls += 1
        return embedding

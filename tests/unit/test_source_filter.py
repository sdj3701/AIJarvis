"""Unit tests for Soft music/speaker source filtering."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.voice.enrollment import (
    SpeakerProfile,
    average_embeddings,
    build_profile_from_frames,
    load_speaker_profile,
    save_speaker_profile,
)
from app.voice.base import AudioFrame
from app.voice.source_filter import (
    MusicSpeechScores,
    SourceFilter,
    SourceFilterPolicy,
    SpeakerSoftMatcher,
    SpectralSpeechMusicClassifier,
    build_music_classifier,
    cosine_similarity,
    l2_normalize,
    voiced_frames,
    window_frames,
)
from tests.fakes.audio_source import (
    ExplodingMusicClassifier,
    FixedMusicClassifier,
    FixedSpeakerEmbedder,
    SequenceSpeakerEmbedder,
    noise_frames,
    sine_frames,
)

pytestmark = pytest.mark.phase7


def _policy(**overrides: object) -> SourceFilterPolicy:
    values: dict[str, object] = {
        "enabled": True,
        "music_enabled": True,
        "speaker_enabled": True,
        "music_reject_threshold": 0.45,
        "speech_margin": 0.05,
        "owner_accept_threshold": 0.75,
        "other_reject_threshold": 0.55,
        "analysis_window_ms": 1_200,
    }
    values.update(overrides)
    return SourceFilterPolicy(**values)  # type: ignore[arg-type]


def test_spectral_classifier_rejects_sustained_tone_as_music() -> None:
    classifier = SpectralSpeechMusicClassifier()
    music = classifier.score(sine_frames())
    speech = classifier.score(noise_frames())

    assert max(music.music, music.singing) > music.speech
    assert speech.speech >= music.speech or speech.speech > max(speech.music, speech.singing)


def test_source_filter_rejects_music_scores() -> None:
    filt = SourceFilter(
        _policy(),
        music_classifier=FixedMusicClassifier(
            MusicSpeechScores(music=0.8, speech=0.1, singing=0.7)
        ),
    )

    decision = filt.classify(sine_frames(), path="wake")

    assert decision.accept is False
    assert decision.label == "music"
    assert decision.music_score == pytest.approx(0.8)


def test_source_filter_accepts_speech_like_scores() -> None:
    filt = SourceFilter(
        _policy(speaker_enabled=False),
        music_classifier=FixedMusicClassifier(
            MusicSpeechScores(music=0.2, speech=0.7, singing=0.1)
        ),
    )

    decision = filt.classify(noise_frames(), path="wake")

    assert decision.accept is True
    assert decision.label == "unknown"


def test_speaker_soft_owner_other_unknown() -> None:
    owner = l2_normalize((1.0, 0.0, 0.0))
    matcher = SpeakerSoftMatcher(
        owner,
        owner_accept_threshold=0.75,
        other_reject_threshold=0.55,
    )

    assert matcher.match((0.99, 0.1, 0.0))[0] == "owner"
    assert matcher.match((0.0, 1.0, 0.0))[0] == "other_speaker"
    mid = l2_normalize((0.65, 0.76, 0.0))
    label, score = matcher.match(mid)
    assert label == "unknown"
    assert 0.55 < score < 0.75


def test_source_filter_soft_speaker_paths() -> None:
    owner = (1.0, 0.0)
    filt = SourceFilter(
        _policy(music_enabled=False),
        music_classifier=None,
        speaker_embedder=FixedSpeakerEmbedder(owner),
        speaker_matcher=SpeakerSoftMatcher(
            owner,
            owner_accept_threshold=0.75,
            other_reject_threshold=0.55,
        ),
    )
    assert filt.classify(noise_frames(), path="command").label == "owner"

    filt_other = SourceFilter(
        _policy(music_enabled=False),
        speaker_embedder=FixedSpeakerEmbedder((0.0, 1.0)),
        speaker_matcher=SpeakerSoftMatcher(
            owner,
            owner_accept_threshold=0.75,
            other_reject_threshold=0.55,
        ),
    )
    decision = filt_other.classify(noise_frames(), path="barge_in")
    assert decision.accept is False
    assert decision.label == "other_speaker"


def test_source_filter_fail_open_on_music_error() -> None:
    filt = SourceFilter(_policy(), music_classifier=ExplodingMusicClassifier())

    decision = filt.classify(sine_frames(), path="wake")

    assert decision.accept is True
    assert decision.reason == "music_classifier_failed"
    assert filt.consume_music_warning() is True


def test_window_frames_keeps_recent_ms() -> None:
    frames = sine_frames(duration_ms=2_000, frame_ms=250)
    window = window_frames(frames, window_ms=1_000)

    assert sum(frame.duration_ms for frame in window) >= 1_000
    assert sum(frame.duration_ms for frame in window) <= 1_250


def test_voiced_frames_prefers_loud_segments() -> None:
    quiet = AudioFrame((100).to_bytes(2, "little", signed=True) * 4_000, 16_000)
    loud = AudioFrame((8_000).to_bytes(2, "little", signed=True) * 4_000, 16_000)
    selected = voiced_frames((quiet, loud, quiet), threshold_dbfs=-42.0, min_ms=200)
    assert selected == (loud,)


def test_build_music_classifier_falls_back_without_onnx(tmp_path: Path) -> None:
    classifier = build_music_classifier(yamnet_model_path=tmp_path / "missing.onnx")
    assert isinstance(classifier, SpectralSpeechMusicClassifier)


def test_enrollment_profile_roundtrip(tmp_path: Path) -> None:
    np = pytest.importorskip("numpy")
    del np
    utterances = [sine_frames(duration_ms=400), noise_frames(duration_ms=400)]
    embedder = SequenceSpeakerEmbedder([(1.0, 0.0), (0.9, 0.1)])
    profile = build_profile_from_frames(
        utterances,
        embedder,
        embedder_id="fake",
    )
    path = tmp_path / "voice" / "speaker_profile.npz"
    save_speaker_profile(path, profile)
    loaded = load_speaker_profile(path)

    assert loaded is not None
    assert loaded.sample_count == 2
    assert loaded.embedder_id == "fake"
    assert cosine_similarity(loaded.embedding, profile.embedding) == pytest.approx(1.0)
    assert not any(tmp_path.rglob("*.wav"))
    assert not any(tmp_path.rglob("*.pcm"))


def test_average_embeddings_normalizes() -> None:
    mean = average_embeddings([(3.0, 0.0), (0.0, 4.0)])
    assert cosine_similarity(mean, l2_normalize((0.6, 0.8))) == pytest.approx(1.0)


def test_load_missing_profile_returns_none(tmp_path: Path) -> None:
    assert load_speaker_profile(tmp_path / "absent.npz") is None


def test_speaker_profile_rejects_empty_embedding() -> None:
    with pytest.raises(ValueError):
        SpeakerProfile(embedding=(), sample_count=1, embedder_id="x")

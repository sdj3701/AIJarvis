"""Tests for engine-neutral voice value objects."""

from __future__ import annotations

import pytest

from app.voice.base import AudioFrame, Transcript

pytestmark = pytest.mark.phase7


def test_audio_frame_is_fixed_to_mono_pcm16() -> None:
    frame = AudioFrame(b"\x00\x00" * 160, sample_rate=16_000)

    assert frame.duration_ms == 10
    assert frame.rms_dbfs == -96.0


def test_audio_frame_reports_pcm_level_in_dbfs() -> None:
    frame = AudioFrame((16_384).to_bytes(2, "little", signed=True) * 160, sample_rate=16_000)

    assert frame.rms_dbfs == pytest.approx(-6.02, abs=0.01)


@pytest.mark.parametrize(
    ("channels", "sample_width"),
    [(2, 2), (1, 1)],
)
def test_audio_frame_rejects_unsupported_format(channels: int, sample_width: int) -> None:
    with pytest.raises(ValueError):
        AudioFrame(
            b"\x00\x00",
            sample_rate=16_000,
            channels=channels,
            sample_width_bytes=sample_width,
        )


def test_transcript_validates_confidence() -> None:
    with pytest.raises(ValueError):
        Transcript("자비스", "ko", 300, 1.1)

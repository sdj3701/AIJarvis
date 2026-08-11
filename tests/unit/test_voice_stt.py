"""Tests for offline Vosk transcription."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from app.voice.base import AudioFrame
from app.voice.stt import VoskRecognizer, VoskSTTEngine, validate_model_directory

pytestmark = pytest.mark.phase7


class FakeRecognizer:
    def __init__(self) -> None:
        self.calls = 0
        self.words = False

    def AcceptWaveform(self, pcm: bytes) -> bool:
        del pcm
        self.calls += 1
        return self.calls == 2

    def Result(self) -> str:
        return json.dumps({"text": "자비스"}, ensure_ascii=False)

    def PartialResult(self) -> str:
        return json.dumps({"partial": "자"}, ensure_ascii=False)

    def FinalResult(self) -> str:
        return json.dumps({"text": "오늘 날씨"}, ensure_ascii=False)

    def SetWords(self, enabled: bool) -> None:
        self.words = enabled


def _model_directory(tmp_path: Path) -> Path:
    model = tmp_path / "model"
    for relative in ("am/final.mdl", "conf/model.conf", "graph/HCLr.fst"):
        path = model / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return model


def test_batch_transcription_keeps_final_segments(tmp_path: Path) -> None:
    recognizers: list[FakeRecognizer] = []

    def factory(model: object, rate: int, grammar: str | None) -> VoskRecognizer:
        del model, rate, grammar
        recognizer = FakeRecognizer()
        recognizers.append(recognizer)
        return recognizer

    engine = VoskSTTEngine(
        _model_directory(tmp_path),
        model_loader=lambda path: object(),
        recognizer_factory=factory,
    )
    frames: Sequence[AudioFrame] = (
        AudioFrame(b"\x00\x00" * 160, 16_000),
        AudioFrame(b"\x01\x00" * 160, 16_000),
    )

    transcript = engine.transcribe(frames)

    assert transcript.text == "자비스 오늘 날씨"
    assert transcript.duration_ms == 20
    assert recognizers[0].words is True


def test_streaming_recognizer_exposes_partial_and_final(tmp_path: Path) -> None:
    engine = VoskSTTEngine(
        _model_directory(tmp_path),
        model_loader=lambda path: object(),
        recognizer_factory=lambda model, rate, grammar: FakeRecognizer(),
    )
    stream = engine.stream(phrases=["자비스"])

    assert stream.feed(b"\x00\x00").text == "자"
    update = stream.feed(b"\x00\x00")
    assert update.final is True
    assert update.text == "자비스"


def test_missing_model_is_reported_without_network_fallback(tmp_path: Path) -> None:
    from app.core.errors import JarvisError

    with pytest.raises(JarvisError) as captured:
        validate_model_directory(tmp_path / "missing")
    assert "setup_voice.py" in captured.value.user_message

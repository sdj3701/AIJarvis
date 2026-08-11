"""Tests for offline Vosk transcription."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.voice.base import AudioFrame, Transcript
from app.voice.stt import (
    FasterWhisperSTTEngine,
    VoskRecognizer,
    VoskSTTEngine,
    transcript_passes_quality,
    validate_model_directory,
)

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
    grammars: list[str | None] = []

    def factory(model: object, rate: int, grammar: str | None) -> VoskRecognizer:
        del model, rate
        grammars.append(grammar)
        return FakeRecognizer()

    engine = VoskSTTEngine(
        _model_directory(tmp_path),
        model_loader=lambda path: object(),
        recognizer_factory=factory,
    )
    stream = engine.stream(phrases=["자비스"])

    assert stream.feed(b"\x00\x00").text == "자"
    update = stream.feed(b"\x00\x00")
    assert update.final is True
    assert update.text == "자비스"
    assert grammars == ['["자비스", "[unk]"]']


def test_missing_model_is_reported_without_network_fallback(tmp_path: Path) -> None:
    from app.core.errors import JarvisError

    with pytest.raises(JarvisError) as captured:
        validate_model_directory(tmp_path / "missing")
    assert "setup_voice.py" in captured.value.user_message


def test_model_archive_hash_must_match_configuration(tmp_path: Path) -> None:
    from app.core.errors import JarvisError

    model = _model_directory(tmp_path)
    model.with_suffix(".zip").write_bytes(b"not-the-pinned-model")

    with pytest.raises(JarvisError) as captured:
        validate_model_directory(model, expected_archive_sha256="0" * 64)
    assert "SHA-256" in captured.value.user_message


@dataclass
class FakeWhisperSegment:
    text: str
    start: float
    end: float
    avg_logprob: float
    no_speech_prob: float


class FakeWhisperModel:
    def __init__(self, segments: list[FakeWhisperSegment]) -> None:
        self.segments = segments
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[list[FakeWhisperSegment], object]:
        self.calls.append({"audio": audio, **kwargs})
        return self.segments, object()


def test_faster_whisper_transcribes_pcm_in_memory_and_reports_quality(tmp_path: Path) -> None:
    model = FakeWhisperModel(
        [FakeWhisperSegment(" 오늘 날짜를 알려줘.", 0.0, 1.0, -0.25, 0.03)]
    )
    engine = FasterWhisperSTTEngine(
        tmp_path / "model",
        expected_model_sha256="1" * 64,
        model_factory=lambda path, device, compute: model,  # type: ignore[arg-type]
        model_validator=lambda path, digest: path,
    )

    transcript = engine.transcribe([AudioFrame(b"\x00\x10" * 16_000, 16_000)])

    assert transcript.text == "오늘 날짜를 알려줘."
    assert transcript.avg_logprob == pytest.approx(-0.25)
    assert transcript.no_speech_probability == pytest.approx(0.03)
    assert transcript.confidence == pytest.approx(0.7788, abs=0.0001)
    assert model.calls[0]["language"] == "ko"
    assert model.calls[0]["beam_size"] == 5
    assert len(model.calls[0]["audio"]) == 16_000
    assert transcript_passes_quality(
        transcript, min_avg_logprob=-1.0, max_no_speech_probability=0.6
    )


def test_faster_whisper_falls_back_to_cpu_once_after_cuda_failure(tmp_path: Path) -> None:
    model = FakeWhisperModel(
        [FakeWhisperSegment("테스트", 0.0, 0.5, -0.2, 0.01)]
    )
    attempts: list[tuple[str, str]] = []

    def factory(path: Path, device: str, compute_type: str) -> Any:
        del path
        attempts.append((device, compute_type))
        if device == "cuda":
            raise RuntimeError("CUDA DLL missing")
        return model

    engine = FasterWhisperSTTEngine(
        tmp_path / "model",
        expected_model_sha256="1" * 64,
        model_factory=factory,
        model_validator=lambda path, digest: path,
    )

    transcript = engine.transcribe([AudioFrame(b"\x00\x00" * 8_000, 16_000)])

    assert transcript.text == "테스트"
    assert engine.active_device == "cpu"
    assert "CUDA DLL missing" in (engine.fallback_reason or "")
    assert attempts == [("cuda", "int8_float16"), ("cpu", "int8")]


def test_quality_guard_rejects_uncertain_or_no_speech_result() -> None:
    uncertain = Transcript("엉뚱한 문장", "ko", 1_000, 0.1, -2.0, 0.8)

    assert not transcript_passes_quality(
        uncertain, min_avg_logprob=-1.0, max_no_speech_probability=0.6
    )

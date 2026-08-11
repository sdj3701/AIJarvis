"""Offline Korean speech recognition backed by a pinned Vosk model."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from app.core.context import RequestContext
from app.core.errors import JarvisError
from app.voice.base import AudioFrame, Transcript

REQUIRED_MODEL_FILES = (
    Path("am/final.mdl"),
    Path("conf/model.conf"),
    Path("graph/HCLr.fst"),
)


class VoskRecognizer(Protocol):
    def AcceptWaveform(self, pcm: bytes) -> bool: ...

    def Result(self) -> str: ...

    def PartialResult(self) -> str: ...

    def FinalResult(self) -> str: ...

    def SetWords(self, enabled: bool) -> None: ...


RecognizerFactory = Callable[[object, int, str | None], VoskRecognizer]


@dataclass(frozen=True, slots=True)
class RecognitionUpdate:
    text: str
    final: bool


def _load_vosk_model(path: Path) -> object:
    try:
        from vosk import Model, SetLogLevel  # type: ignore[import-untyped]
    except ImportError as error:
        raise JarvisError(
            "음성 인식 패키지가 없습니다. pip install -e .[voice]를 실행하세요."
        ) from error
    SetLogLevel(-1)
    return cast(object, Model(str(path)))


def _recognizer_factory(model: object, sample_rate: int, grammar: str | None) -> VoskRecognizer:
    from vosk import KaldiRecognizer

    recognizer = (
        KaldiRecognizer(model, sample_rate, grammar)
        if grammar is not None
        else KaldiRecognizer(model, sample_rate)
    )
    return cast(VoskRecognizer, recognizer)


def validate_model_directory(path: Path) -> Path:
    resolved = Path(path).resolve(strict=False)
    missing = [
        str(relative)
        for relative in REQUIRED_MODEL_FILES
        if not (resolved / relative).is_file()
    ]
    if missing:
        raise JarvisError(
            "한국어 음성 인식 모델이 없습니다. python scripts\\setup_voice.py를 실행하세요.",
            {"model": resolved.name, "missing": missing},
        )
    return resolved


def _text_from_result(encoded: str, field: str) -> str:
    try:
        document = json.loads(encoded)
    except json.JSONDecodeError as error:
        raise JarvisError("음성 인식 결과 형식이 올바르지 않습니다.") from error
    value = document.get(field)
    if not isinstance(value, str):
        raise JarvisError("음성 인식 결과에 텍스트가 없습니다.")
    return value.strip()


class VoskStreamingRecognizer:
    def __init__(self, recognizer: VoskRecognizer) -> None:
        self._recognizer = recognizer

    def feed(self, pcm: bytes) -> RecognitionUpdate:
        if self._recognizer.AcceptWaveform(pcm):
            return RecognitionUpdate(_text_from_result(self._recognizer.Result(), "text"), True)
        return RecognitionUpdate(
            _text_from_result(self._recognizer.PartialResult(), "partial"), False
        )

    def finish(self) -> RecognitionUpdate:
        return RecognitionUpdate(_text_from_result(self._recognizer.FinalResult(), "text"), True)


class VoskSTTEngine:
    """Load one local model and create independent batch or streaming recognizers."""

    def __init__(
        self,
        model_path: Path,
        *,
        sample_rate: int = 16_000,
        language: str = "ko",
        model_loader: Callable[[Path], object] = _load_vosk_model,
        recognizer_factory: RecognizerFactory = _recognizer_factory,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        self._model_path = validate_model_directory(model_path)
        self._sample_rate = sample_rate
        self._language = language
        self._model = model_loader(self._model_path)
        self._recognizer_factory = recognizer_factory

    def stream(self, *, phrases: Sequence[str] | None = None) -> VoskStreamingRecognizer:
        grammar = None
        if phrases is not None:
            grammar = json.dumps([*phrases, "[unk]"], ensure_ascii=False)
        recognizer = self._recognizer_factory(self._model, self._sample_rate, grammar)
        return VoskStreamingRecognizer(recognizer)

    def transcribe(
        self,
        frames: Sequence[AudioFrame],
        *,
        ctx: RequestContext | None = None,
    ) -> Transcript:
        if not frames:
            return Transcript("", self._language, 0, None)
        if ctx is not None:
            ctx.cancel.raise_if_cancelled()
        recognizer = self._recognizer_factory(self._model, self._sample_rate, None)
        recognizer.SetWords(True)
        texts: list[str] = []
        duration_ms = 0
        for frame in frames:
            if frame.sample_rate != self._sample_rate:
                raise ValueError("audio sample rate does not match the Vosk engine")
            if ctx is not None:
                ctx.cancel.raise_if_cancelled()
            duration_ms += frame.duration_ms
            if recognizer.AcceptWaveform(frame.pcm):
                text = _text_from_result(recognizer.Result(), "text")
                if text:
                    texts.append(text)
        final = _text_from_result(recognizer.FinalResult(), "text")
        if final:
            texts.append(final)
        return Transcript(" ".join(texts).strip(), self._language, duration_ms, None)

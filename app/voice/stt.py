"""Pinned local Korean recognition for Vosk wake words and Whisper questions."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast

from app.core.context import RequestContext
from app.core.errors import JarvisError
from app.voice.base import AudioFrame, Transcript

REQUIRED_MODEL_FILES = (
    Path("am/final.mdl"),
    Path("conf/model.conf"),
    Path("graph/HCLr.fst"),
)
WHISPER_REQUIRED_MODEL_FILES = (
    Path("config.json"),
    Path("model.bin"),
    Path("tokenizer.json"),
    Path("vocabulary.txt"),
)


class VoskRecognizer(Protocol):
    def AcceptWaveform(self, pcm: bytes) -> bool: ...

    def Result(self) -> str: ...

    def PartialResult(self) -> str: ...

    def FinalResult(self) -> str: ...

    def SetWords(self, enabled: bool) -> None: ...


RecognizerFactory = Callable[[object, int, str | None], VoskRecognizer]


class WhisperSegment(Protocol):
    text: str
    start: float
    end: float
    avg_logprob: float
    no_speech_prob: float


class WhisperModel(Protocol):
    def transcribe(
        self, audio: Any, **kwargs: Any
    ) -> tuple[Iterable[WhisperSegment], object]: ...


WhisperModelFactory = Callable[[Path, str, str], WhisperModel]
WhisperModelValidator = Callable[[Path, str], Path]


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_model_directory(
    path: Path,
    *,
    expected_archive_sha256: str | None = None,
) -> Path:
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
    if expected_archive_sha256 is not None:
        archive = resolved.parent / f"{resolved.name}.zip"
        if not archive.is_file() or _sha256(archive) != expected_archive_sha256:
            raise JarvisError(
                "한국어 음성 인식 모델의 SHA-256 검증에 실패했습니다.",
                {"model": resolved.name},
            )
    return resolved


def validate_whisper_model_directory(path: Path, expected_model_sha256: str) -> Path:
    resolved = Path(path).resolve(strict=False)
    missing = [
        str(relative)
        for relative in WHISPER_REQUIRED_MODEL_FILES
        if not (resolved / relative).is_file()
    ]
    if missing:
        raise JarvisError(
            "Whisper 질문 인식 모델이 없습니다. python scripts\\setup_voice.py를 실행하세요.",
            {"model": resolved.name, "missing": missing},
        )
    if _sha256(resolved / "model.bin") != expected_model_sha256:
        raise JarvisError(
            "Whisper 질문 인식 모델의 SHA-256 검증에 실패했습니다.",
            {"model": resolved.name},
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
        expected_archive_sha256: str | None = None,
        model_loader: Callable[[Path], object] = _load_vosk_model,
        recognizer_factory: RecognizerFactory = _recognizer_factory,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        self._model_path = validate_model_directory(
            model_path,
            expected_archive_sha256=expected_archive_sha256,
        )
        self._sample_rate = sample_rate
        self._language = language
        self._model = model_loader(self._model_path)
        self._recognizer_factory = recognizer_factory

    def stream(self, *, phrases: Sequence[str] | None = None) -> VoskStreamingRecognizer:
        grammar = None
        if phrases is not None:
            grammar = json.dumps(list(phrases), ensure_ascii=False)
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


def _whisper_model_factory(path: Path, device: str, compute_type: str) -> WhisperModel:
    try:
        module = import_module("faster_whisper")
    except ImportError as error:
        raise JarvisError(
            "Whisper 패키지가 없습니다. pip install -e .[voice]를 실행하세요."
        ) from error
    return cast(
        WhisperModel,
        module.WhisperModel(str(path), device=device, compute_type=compute_type),
    )


def transcript_passes_quality(
    transcript: Transcript,
    *,
    min_avg_logprob: float,
    max_no_speech_probability: float,
) -> bool:
    return bool(
        transcript.text.strip()
        and transcript.avg_logprob is not None
        and transcript.avg_logprob >= min_avg_logprob
        and transcript.no_speech_probability is not None
        and transcript.no_speech_probability <= max_no_speech_probability
    )


class FasterWhisperSTTEngine:
    """Lazy local Whisper model with one explicit CUDA-to-CPU fallback."""

    def __init__(
        self,
        model_path: Path,
        *,
        expected_model_sha256: str,
        language: str = "ko",
        device: str = "cuda",
        compute_type: str = "int8_float16",
        cpu_fallback: bool = True,
        cpu_compute_type: str = "int8",
        beam_size: int = 5,
        vad_filter: bool = True,
        initial_prompt: str = "한국어 자비스 음성 비서 질문입니다.",
        model_factory: WhisperModelFactory = _whisper_model_factory,
        model_validator: WhisperModelValidator = validate_whisper_model_directory,
    ) -> None:
        if beam_size <= 0:
            raise ValueError("beam_size must be positive")
        self._model_path = model_validator(model_path, expected_model_sha256)
        self._language = language
        self._preferred_device = device
        self._preferred_compute_type = compute_type
        self._cpu_fallback = cpu_fallback
        self._cpu_compute_type = cpu_compute_type
        self._beam_size = beam_size
        self._vad_filter = vad_filter
        self._initial_prompt = initial_prompt
        self._model_factory = model_factory
        self._model: WhisperModel | None = None
        self._active_device = device
        self._fallback_reason: str | None = None

    @property
    def active_device(self) -> str:
        return self._active_device

    @property
    def fallback_reason(self) -> str | None:
        return self._fallback_reason

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
        sample_rate = frames[0].sample_rate
        if any(frame.sample_rate != sample_rate for frame in frames):
            raise ValueError("all audio frames must have the same sample rate")
        if sample_rate != 16_000:
            raise ValueError("faster-whisper input must be 16 kHz")
        audio = _frames_to_float32(frames)
        try:
            return self._transcribe(audio, frames, ctx=ctx)
        except Exception as error:
            if self._active_device != "cuda" or not self._cpu_fallback:
                raise
            self._model = None
            self._active_device = "cpu"
            self._fallback_reason = f"{type(error).__name__}: {error}"
            return self._transcribe(audio, frames, ctx=ctx)

    def _transcribe(
        self,
        audio: Any,
        frames: Sequence[AudioFrame],
        *,
        ctx: RequestContext | None,
    ) -> Transcript:
        if self._model is None:
            compute_type = (
                self._cpu_compute_type
                if self._active_device == "cpu"
                else self._preferred_compute_type
            )
            self._model = self._model_factory(
                self._model_path,
                self._active_device,
                compute_type,
            )
        segments_iter, _info = self._model.transcribe(
            audio,
            language=self._language,
            task="transcribe",
            beam_size=self._beam_size,
            vad_filter=self._vad_filter,
            initial_prompt=self._initial_prompt,
            condition_on_previous_text=False,
        )
        segments = list(segments_iter)
        if ctx is not None:
            ctx.cancel.raise_if_cancelled()
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        duration_ms = sum(frame.duration_ms for frame in frames)
        if not segments:
            return Transcript("", self._language, duration_ms, None)
        weights = [max(0.001, segment.end - segment.start) for segment in segments]
        total_weight = sum(weights)
        avg_logprob = sum(
            segment.avg_logprob * weight for segment, weight in zip(segments, weights, strict=True)
        ) / total_weight
        no_speech_probability = max(segment.no_speech_prob for segment in segments)
        confidence = max(0.0, min(1.0, math.exp(avg_logprob)))
        return Transcript(
            text.strip(),
            self._language,
            duration_ms,
            confidence,
            avg_logprob,
            no_speech_probability,
        )


def _frames_to_float32(frames: Sequence[AudioFrame]) -> Any:
    try:
        np = import_module("numpy")
    except ImportError as error:
        raise JarvisError(
            "Whisper 오디오 변환 패키지가 없습니다. pip install -e .[voice]를 실행하세요."
        ) from error
    pcm = b"".join(frame.pcm for frame in frames)
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32_768.0

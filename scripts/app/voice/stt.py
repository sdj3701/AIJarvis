# 파이썬 공부 | scripts/app/voice/stt.py
# Vosk로 호출어를 인식하고 Whisper로 질문 음성을 글자로 바꿉니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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

# REQUIRED_MODEL_FILES에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
REQUIRED_MODEL_FILES = (
    Path("am/final.mdl"),
    Path("conf/model.conf"),
    Path("graph/HCLr.fst"),
)
# WHISPER_REQUIRED_MODEL_FILES에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
WHISPER_REQUIRED_MODEL_FILES = (
    Path("config.json"),
    Path("model.bin"),
    Path("tokenizer.json"),
    Path("vocabulary.txt"),
)


# VoskRecognizer: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class VoskRecognizer(Protocol):
    # AcceptWaveform(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: pcm.
    # 반환 타입 힌트: 참/거짓(bool).
    def AcceptWaveform(self, pcm: bytes) -> bool: ...

    # Result(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    def Result(self) -> str: ...

    # PartialResult(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    def PartialResult(self) -> str: ...

    # FinalResult(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    def FinalResult(self) -> str: ...

    # SetWords(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: enabled.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def SetWords(self, enabled: bool) -> None: ...


# 오른쪽 식을 계산한 값을 RecognizerFactory에 대입합니다.
RecognizerFactory = Callable[[object, int, str | None], VoskRecognizer]


# WhisperSegment: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class WhisperSegment(Protocol):
    # text: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    text: str
    # start: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    start: float
    # end: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    end: float
    # avg_logprob: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    avg_logprob: float
    # no_speech_prob: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    no_speech_prob: float


# WhisperModel: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class WhisperModel(Protocol):
    # transcribe(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: audio.
    # **kwargs는 추가 이름 인자를 딕셔너리로 모읍니다.
    # 반환 타입 힌트: tuple[Iterable[WhisperSegment], object].
    def transcribe(
        self, audio: Any, **kwargs: Any
    ) -> tuple[Iterable[WhisperSegment], object]: ...


# 오른쪽 식을 계산한 값을 WhisperModelFactory에 대입합니다.
WhisperModelFactory = Callable[[Path, str, str], WhisperModel]
# 오른쪽 식을 계산한 값을 WhisperModelValidator에 대입합니다.
WhisperModelValidator = Callable[[Path, str], Path]


# RecognitionUpdate: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class RecognitionUpdate:
    # text: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    text: str
    # final: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    final: bool


# _load_vosk_model(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: object.
def _load_vosk_model(path: Path) -> object:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        from vosk import Model, SetLogLevel
    # ImportError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except ImportError as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise JarvisError(
            "음성 인식 패키지가 없습니다. pip install -e .[voice]를 실행하세요."
        ) from error
    # SetLogLevel()을 호출해 작업을 수행합니다.
    SetLogLevel(-1)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return cast(object, Model(str(path)))


# _recognizer_factory(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: model, sample_rate, grammar.
# 반환 타입 힌트: VoskRecognizer.
def _recognizer_factory(model: object, sample_rate: int, grammar: str | None) -> VoskRecognizer:
    from vosk import KaldiRecognizer

    # 오른쪽 식을 계산한 값을 recognizer에 대입합니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    recognizer = (
        KaldiRecognizer(model, sample_rate, grammar)
        if grammar is not None
        else KaldiRecognizer(model, sample_rate)
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return cast(VoskRecognizer, recognizer)


# _sha256(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: 문자열(str).
def _sha256(path: Path) -> str:
    # hashlib.sha256()의 반환값을 digest에 대입합니다.
    digest = hashlib.sha256()
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with path.open("rb") as source:
        # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
        while chunk := source.read(1024 * 1024):
            # digest.update()을 호출해 작업을 수행합니다.
            digest.update(chunk)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return digest.hexdigest()


# validate_model_directory(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, expected_archive_sha256.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: Path.
def validate_model_directory(
    path: Path,
    *,
    expected_archive_sha256: str | None = None,
) -> Path:
    # Path(path).resolve()의 반환값을 resolved에 대입합니다.
    resolved = Path(path).resolve(strict=False)
    # 오른쪽 식을 계산한 값을 missing에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    missing = [
        str(relative)
        for relative in REQUIRED_MODEL_FILES
        if not (resolved / relative).is_file()
    ]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: missing.
    if missing:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise JarvisError(
            "한국어 음성 인식 모델이 없습니다. python scripts\\setup_voice.py를 실행하세요.",
            {"model": resolved.name, "missing": missing},
        )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: expected_archive_sha256 is not None.
    if expected_archive_sha256 is not None:
        # 오른쪽 식을 계산한 값을 archive에 대입합니다.
        archive = resolved.parent / f"{resolved.name}.zip"
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not archive.is_file() or _sha256(archive) != expected_archive_sha256:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise JarvisError(
                "한국어 음성 인식 모델의 SHA-256 검증에 실패했습니다.",
                {"model": resolved.name},
            )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return resolved


# validate_whisper_model_directory(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, expected_model_sha256.
# 반환 타입 힌트: Path.
def validate_whisper_model_directory(path: Path, expected_model_sha256: str) -> Path:
    # Path(path).resolve()의 반환값을 resolved에 대입합니다.
    resolved = Path(path).resolve(strict=False)
    # 오른쪽 식을 계산한 값을 missing에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    missing = [
        str(relative)
        for relative in WHISPER_REQUIRED_MODEL_FILES
        if not (resolved / relative).is_file()
    ]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: missing.
    if missing:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise JarvisError(
            "Whisper 질문 인식 모델이 없습니다. python scripts\\setup_voice.py를 실행하세요.",
            {"model": resolved.name, "missing": missing},
        )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _sha256(resolved / 'model.bin') !=
    # expected_model_sha256.
    if _sha256(resolved / "model.bin") != expected_model_sha256:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise JarvisError(
            "Whisper 질문 인식 모델의 SHA-256 검증에 실패했습니다.",
            {"model": resolved.name},
        )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return resolved


# _text_from_result(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: encoded, field.
# 반환 타입 힌트: 문자열(str).
def _text_from_result(encoded: str, field: str) -> str:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # json.loads()의 반환값을 document에 대입합니다.
        document = json.loads(encoded)
    # json.JSONDecodeError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except json.JSONDecodeError as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise JarvisError("음성 인식 결과 형식이 올바르지 않습니다.") from error
    # document.get()의 반환값을 value에 대입합니다.
    value = document.get(field)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(value, str).
    if not isinstance(value, str):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise JarvisError("음성 인식 결과에 텍스트가 없습니다.")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return value.strip()


# VoskStreamingRecognizer: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class VoskStreamingRecognizer:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: recognizer.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, recognizer: VoskRecognizer) -> None:
        # 오른쪽 식을 계산한 값을 self._recognizer에 대입합니다.
        self._recognizer = recognizer

    # feed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: pcm.
    # 반환 타입 힌트: RecognitionUpdate.
    def feed(self, pcm: bytes) -> RecognitionUpdate:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._recognizer.AcceptWaveform(pcm).
        if self._recognizer.AcceptWaveform(pcm):
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return RecognitionUpdate(_text_from_result(self._recognizer.Result(), "text"), True)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return RecognitionUpdate(
            _text_from_result(self._recognizer.PartialResult(), "partial"), False
        )

    # finish(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: RecognitionUpdate.
    def finish(self) -> RecognitionUpdate:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return RecognitionUpdate(_text_from_result(self._recognizer.FinalResult(), "text"), True)


# VoskSTTEngine: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class VoskSTTEngine:
    """Load one local model and create independent batch or streaming recognizers."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: model_path, sample_rate, language, expected_archive_sha256, model_loader,
    # recognizer_factory.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
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
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: sample_rate <= 0.
        if sample_rate <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("sample_rate must be positive")
        # validate_model_directory()의 반환값을 self._model_path에 대입합니다.
        self._model_path = validate_model_directory(
            model_path,
            expected_archive_sha256=expected_archive_sha256,
        )
        # 오른쪽 식을 계산한 값을 self._sample_rate에 대입합니다.
        self._sample_rate = sample_rate
        # 오른쪽 식을 계산한 값을 self._language에 대입합니다.
        self._language = language
        # model_loader()의 반환값을 self._model에 대입합니다.
        self._model = model_loader(self._model_path)
        # 오른쪽 식을 계산한 값을 self._recognizer_factory에 대입합니다.
        self._recognizer_factory = recognizer_factory

    # stream(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: phrases.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: VoskStreamingRecognizer.
    def stream(self, *, phrases: Sequence[str] | None = None) -> VoskStreamingRecognizer:
        # grammar을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        grammar = None
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: phrases is not None.
        if phrases is not None:
            # Include [unk] so non-wake speech is not forced into the wake phrases.
            # json.dumps()의 반환값을 grammar에 대입합니다.
            grammar = json.dumps([*phrases, "[unk]"], ensure_ascii=False)
        # self._recognizer_factory()의 반환값을 recognizer에 대입합니다.
        recognizer = self._recognizer_factory(self._model, self._sample_rate, grammar)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return VoskStreamingRecognizer(recognizer)

    # transcribe(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: frames, ctx.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: Transcript.
    def transcribe(
        self,
        frames: Sequence[AudioFrame],
        *,
        ctx: RequestContext | None = None,
    ) -> Transcript:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not frames.
        if not frames:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return Transcript("", self._language, 0, None)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ctx is not None.
        if ctx is not None:
            # ctx.cancel.raise_if_cancelled()을 호출해 작업을 수행합니다.
            ctx.cancel.raise_if_cancelled()
        # self._recognizer_factory()의 반환값을 recognizer에 대입합니다.
        recognizer = self._recognizer_factory(self._model, self._sample_rate, None)
        # recognizer.SetWords()을 호출해 작업을 수행합니다.
        recognizer.SetWords(True)
        # texts에 리스트(순서가 있고 수정 가능)을 대입합니다.
        texts: list[str] = []
        # duration_ms에 숫자 등 고정된 값을 대입합니다.
        duration_ms = 0
        # for 반복문: 대상의 항목을 하나씩 frame에 대입하며 아래 블록을 실행합니다.
        for frame in frames:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: frame.sample_rate !=
            # self._sample_rate.
            if frame.sample_rate != self._sample_rate:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise ValueError("audio sample rate does not match the Vosk engine")
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ctx is not None.
            if ctx is not None:
                # ctx.cancel.raise_if_cancelled()을 호출해 작업을 수행합니다.
                ctx.cancel.raise_if_cancelled()
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            duration_ms += frame.duration_ms
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다:
            # recognizer.AcceptWaveform(frame.pcm).
            if recognizer.AcceptWaveform(frame.pcm):
                # _text_from_result()의 반환값을 text에 대입합니다.
                text = _text_from_result(recognizer.Result(), "text")
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: text.
                if text:
                    # 리스트 끝에 항목 하나를 추가합니다.
                    texts.append(text)
        # _text_from_result()의 반환값을 final에 대입합니다.
        final = _text_from_result(recognizer.FinalResult(), "text")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: final.
        if final:
            # 리스트 끝에 항목 하나를 추가합니다.
            texts.append(final)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return Transcript(" ".join(texts).strip(), self._language, duration_ms, None)


# _whisper_model_factory(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, device, compute_type.
# 반환 타입 힌트: WhisperModel.
def _whisper_model_factory(path: Path, device: str, compute_type: str) -> WhisperModel:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # import_module()의 반환값을 module에 대입합니다.
        module = import_module("faster_whisper")
    # ImportError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except ImportError as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise JarvisError(
            "Whisper 패키지가 없습니다. pip install -e .[voice]를 실행하세요."
        ) from error
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return cast(
        WhisperModel,
        module.WhisperModel(str(path), device=device, compute_type=compute_type),
    )


# transcript_passes_quality(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: transcript, min_avg_logprob, max_no_speech_probability.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 참/거짓(bool).
def transcript_passes_quality(
    transcript: Transcript,
    *,
    min_avg_logprob: float,
    max_no_speech_probability: float,
) -> bool:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return bool(
        transcript.text.strip()
        and transcript.avg_logprob is not None
        and transcript.avg_logprob >= min_avg_logprob
        and transcript.no_speech_probability is not None
        and transcript.no_speech_probability <= max_no_speech_probability
    )


# FasterWhisperSTTEngine: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FasterWhisperSTTEngine:
    """Lazy local Whisper model with one explicit CUDA-to-CPU fallback."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: model_path, expected_model_sha256, language, device, compute_type, cpu_fallback,
    # cpu_compute_type, beam_size, vad_filter, initial_prompt, model_factory, model_validator.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
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
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: beam_size <= 0.
        if beam_size <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("beam_size must be positive")
        # model_validator()의 반환값을 self._model_path에 대입합니다.
        self._model_path = model_validator(model_path, expected_model_sha256)
        # 오른쪽 식을 계산한 값을 self._language에 대입합니다.
        self._language = language
        # 오른쪽 식을 계산한 값을 self._preferred_device에 대입합니다.
        self._preferred_device = device
        # 오른쪽 식을 계산한 값을 self._preferred_compute_type에 대입합니다.
        self._preferred_compute_type = compute_type
        # 오른쪽 식을 계산한 값을 self._cpu_fallback에 대입합니다.
        self._cpu_fallback = cpu_fallback
        # 오른쪽 식을 계산한 값을 self._cpu_compute_type에 대입합니다.
        self._cpu_compute_type = cpu_compute_type
        # 오른쪽 식을 계산한 값을 self._beam_size에 대입합니다.
        self._beam_size = beam_size
        # 오른쪽 식을 계산한 값을 self._vad_filter에 대입합니다.
        self._vad_filter = vad_filter
        # 오른쪽 식을 계산한 값을 self._initial_prompt에 대입합니다.
        self._initial_prompt = initial_prompt
        # 오른쪽 식을 계산한 값을 self._model_factory에 대입합니다.
        self._model_factory = model_factory
        # self._model을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        self._model: WhisperModel | None = None
        # 오른쪽 식을 계산한 값을 self._active_device에 대입합니다.
        self._active_device = device
        # self._fallback_reason을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        self._fallback_reason: str | None = None

    # active_device(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def active_device(self) -> str:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._active_device

    # fallback_reason(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: str | None.
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def fallback_reason(self) -> str | None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._fallback_reason

    # transcribe(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: frames, ctx.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: Transcript.
    def transcribe(
        self,
        frames: Sequence[AudioFrame],
        *,
        ctx: RequestContext | None = None,
    ) -> Transcript:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not frames.
        if not frames:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return Transcript("", self._language, 0, None)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ctx is not None.
        if ctx is not None:
            # ctx.cancel.raise_if_cancelled()을 호출해 작업을 수행합니다.
            ctx.cancel.raise_if_cancelled()
        # 오른쪽 식을 계산한 값을 sample_rate에 대입합니다.
        sample_rate = frames[0].sample_rate
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: any((frame.sample_rate != sample_rate
        # for frame in
        # frames)).
        if any(frame.sample_rate != sample_rate for frame in frames):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("all audio frames must have the same sample rate")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: sample_rate != 16000.
        if sample_rate != 16_000:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("faster-whisper input must be 16 kHz")
        # _frames_to_float32()의 반환값을 audio에 대입합니다.
        audio = _frames_to_float32(frames)
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return self._transcribe(audio, frames, ctx=ctx)
        # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except Exception as error:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._active_device != 'cuda' or
            # not
            # self._cpu_fallback.
            if self._active_device != "cuda" or not self._cpu_fallback:
                # 현재 예외를 다시 발생시켜 호출한 쪽으로 전달합니다.
                raise
            # self._model을 아직 값이 없음을 뜻하는 None으로 설정합니다.
            self._model = None
            # self._active_device에 문자열을 대입합니다.
            self._active_device = "cpu"
            # 오른쪽 식을 계산한 값을 self._fallback_reason에 대입합니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            self._fallback_reason = f"{type(error).__name__}: {error}"
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return self._transcribe(audio, frames, ctx=ctx)

    # _transcribe(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: audio, frames, ctx.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: Transcript.
    def _transcribe(
        self,
        audio: Any,
        frames: Sequence[AudioFrame],
        *,
        ctx: RequestContext | None,
    ) -> Transcript:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._model is None.
        if self._model is None:
            # 오른쪽 식을 계산한 값을 compute_type에 대입합니다.
            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
            compute_type = (
                self._cpu_compute_type
                if self._active_device == "cpu"
                else self._preferred_compute_type
            )
            # self._model_factory()의 반환값을 self._model에 대입합니다.
            self._model = self._model_factory(
                self._model_path,
                self._active_device,
                compute_type,
            )
        # 언패킹: 오른쪽 결과를 순서대로 (segments_iter, _info)에 나누어 담습니다.
        segments_iter, _info = self._model.transcribe(
            audio,
            language=self._language,
            task="transcribe",
            beam_size=self._beam_size,
            vad_filter=self._vad_filter,
            initial_prompt=self._initial_prompt,
            condition_on_previous_text=False,
        )
        # list()의 반환값을 segments에 대입합니다.
        segments = list(segments_iter)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ctx is not None.
        if ctx is not None:
            # ctx.cancel.raise_if_cancelled()을 호출해 작업을 수행합니다.
            ctx.cancel.raise_if_cancelled()
        # ' '.join()의 반환값을 text에 대입합니다.
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        # sum()의 반환값을 duration_ms에 대입합니다.
        duration_ms = sum(frame.duration_ms for frame in frames)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not segments.
        if not segments:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return Transcript("", self._language, duration_ms, None)
        # 오른쪽 식을 계산한 값을 weights에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        weights = [max(0.001, segment.end - segment.start) for segment in segments]
        # sum()의 반환값을 total_weight에 대입합니다.
        total_weight = sum(weights)
        # 오른쪽 식을 계산한 값을 avg_logprob에 대입합니다.
        avg_logprob = sum(
            segment.avg_logprob * weight for segment, weight in zip(segments, weights, strict=True)
        ) / total_weight
        # max()의 반환값을 no_speech_probability에 대입합니다.
        no_speech_probability = max(segment.no_speech_prob for segment in segments)
        # max()의 반환값을 confidence에 대입합니다.
        confidence = max(0.0, min(1.0, math.exp(avg_logprob)))
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return Transcript(
            text.strip(),
            self._language,
            duration_ms,
            confidence,
            avg_logprob,
            no_speech_probability,
        )


# _frames_to_float32(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: frames.
# 반환 타입 힌트: 어떤 타입이든 허용(Any).
def _frames_to_float32(frames: Sequence[AudioFrame]) -> Any:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # import_module()의 반환값을 np에 대입합니다.
        np = import_module("numpy")
    # ImportError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except ImportError as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise JarvisError(
            "Whisper 오디오 변환 패키지가 없습니다. pip install -e .[voice]를 실행하세요."
        ) from error
    # b''.join()의 반환값을 pcm에 대입합니다.
    pcm = b"".join(frame.pcm for frame in frames)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32_768.0

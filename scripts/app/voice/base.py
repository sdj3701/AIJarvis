# 파이썬 공부 | scripts/app/voice/base.py
# 음성 인식과 합성 엔진에서 공유할 데이터와 규약을 정의합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Engine-neutral voice contracts."""

from __future__ import annotations

import array
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.core.context import RequestContext


# AudioFrame: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class AudioFrame:
    # pcm: 바이트 데이터(bytes) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    pcm: bytes
    # sample_rate: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    sample_rate: int
    # channels에 숫자 등 고정된 값을 대입합니다.
    channels: int = 1
    # sample_width_bytes에 숫자 등 고정된 값을 대입합니다.
    sample_width_bytes: int = 2

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(self.pcm, bytes).
        if not isinstance(self.pcm, bytes):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError("AudioFrame.pcm must be bytes")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(self.sample_rate, int)
        # or self.sample_rate
        # <= 0.
        if not isinstance(self.sample_rate, int) or self.sample_rate <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("AudioFrame.sample_rate must be a positive integer")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.channels != 1.
        if self.channels != 1:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("voice audio must be mono")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.sample_width_bytes != 2.
        if self.sample_width_bytes != 2:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("voice audio must be 16-bit PCM")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(self.pcm) %
        # self.sample_width_bytes.
        if len(self.pcm) % self.sample_width_bytes:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("PCM byte length must align to the sample width")

    # duration_ms(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 정수(int).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def duration_ms(self) -> int:
        # 오른쪽 식을 계산한 값을 samples에 대입합니다.
        samples = len(self.pcm) // self.sample_width_bytes
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return samples * 1000 // self.sample_rate

    # rms_dbfs(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 실수(float).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def rms_dbfs(self) -> float:
        """Return the PCM16 RMS level in dBFS without persisting audio."""
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self.pcm.
        if not self.pcm:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return -96.0
        # array.array()의 반환값을 samples에 대입합니다.
        samples = array.array("h")
        # samples.frombytes()을 호출해 작업을 수행합니다.
        samples.frombytes(self.pcm)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: sys.byteorder != 'little'.
        if sys.byteorder != "little":
            # samples.byteswap()을 호출해 작업을 수행합니다.
            samples.byteswap()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not samples.
        if not samples:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return -96.0
        # 오른쪽 식을 계산한 값을 mean_square에 대입합니다.
        mean_square = sum(sample * sample for sample in samples) / len(samples)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: mean_square <= 0.
        if mean_square <= 0:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return -96.0
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return max(-96.0, 20 * math.log10(math.sqrt(mean_square) / 32_768))


# Transcript: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class Transcript:
    # text: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    text: str
    # language: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    language: str
    # duration_ms: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    duration_ms: int
    # confidence: float | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    confidence: float | None
    # avg_logprob을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    avg_logprob: float | None = None
    # no_speech_probability을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    no_speech_probability: float | None = None

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(self.text, str).
        if not isinstance(self.text, str):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError("Transcript.text must be a string")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self.language.
        if not self.language:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("Transcript.language must not be empty")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.duration_ms < 0.
        if self.duration_ms < 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("Transcript.duration_ms must not be negative")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.confidence is not None and (not 0
        # <= self.confidence
        # <= 1).
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("Transcript.confidence must be between zero and one")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.avg_logprob is not None and
        # self.avg_logprob > 0.
        if self.avg_logprob is not None and self.avg_logprob > 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("Transcript.avg_logprob must not be positive")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if self.no_speech_probability is not None and not 0 <= self.no_speech_probability <= 1:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("Transcript.no_speech_probability must be between zero and one")


# STTEngine: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class STTEngine(Protocol):
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
    ) -> Transcript: ...


# TTSEngine: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class TTSEngine(Protocol):
    # speak(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text, ctx.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def speak(self, text: str, *, ctx: RequestContext | None = None) -> None: ...

    # cancel(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def cancel(self) -> None: ...

    # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def close(self) -> None: ...

# 파이썬 공부 | scripts/tests/fakes/audio.py
# 실제 마이크와 스피커 대신 제어 가능한 테스트용 음성 객체를 제공합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Deterministic audio fakes for offline Phase 7 tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any

from app.voice.base import AudioFrame, Transcript
from app.voice.microphone import InputDevice, OpenAudioStream


# FakeAudioStream: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class FakeAudioStream:
    # field()의 반환값을 frames에 대입합니다.
    frames: list[AudioFrame] = field(default_factory=list)
    # overflows에 숫자 등 고정된 값을 대입합니다.
    overflows: int = 0
    # closed을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    closed: bool = False
    # entered을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    entered: bool = False

    # __enter__(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: FakeAudioStream.
    def __enter__(self) -> FakeAudioStream:
        # self.entered을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.entered = True
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self

    # __exit__(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: exc_type, exc_val, exc_tb.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        # 사용하던 연결이나 자원을 닫습니다.
        self.close()

    # read(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: timeout_s.
    # 반환 타입 힌트: AudioFrame | None.
    def read(self, timeout_s: float | None = None) -> AudioFrame | None:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del timeout_s
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.closed or not self.frames.
        if self.closed or not self.frames:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.frames.pop(0)

    # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def close(self) -> None:
        # self.closed을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.closed = True


# FakeOpenStream: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeOpenStream:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # self.started을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.started = False
        # self.stopped을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.stopped = False
        # self.closed을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.closed = False

    # start(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def start(self) -> None:
        # self.started을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.started = True

    # stop(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def stop(self) -> None:
        # self.stopped을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.stopped = True

    # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def close(self) -> None:
        # self.closed을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.closed = True


# FakeAudioBackend: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class FakeAudioBackend:
    # field()의 반환값을 devices_list에 대입합니다.
    devices_list: list[InputDevice] = field(default_factory=list)
    # default_index에 숫자 등 고정된 값을 대입합니다.
    default_index: int | None = 0
    # last_callback을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    last_callback: Callable[[bytes, bool], None] | None = None
    # field()의 반환값을 stream에 대입합니다.
    stream: FakeOpenStream = field(default_factory=FakeOpenStream)

    # devices(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Sequence[InputDevice].
    def devices(self) -> Sequence[InputDevice]:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self.devices_list.
        if not self.devices_list:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return (InputDevice(0, "Fake Microphone", 1),)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return tuple(self.devices_list)

    # default_input(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: int | None.
    def default_input(self) -> int | None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.default_index

    # open_input(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: device, sample_rate, block_size, callback.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: OpenAudioStream.
    def open_input(
        self,
        *,
        device: int,
        sample_rate: int,
        block_size: int,
        callback: Callable[[bytes, bool], None],
    ) -> OpenAudioStream:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del device, sample_rate, block_size
        # 오른쪽 식을 계산한 값을 self.last_callback에 대입합니다.
        self.last_callback = callback
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.stream


# FakeSTTEngine: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class FakeSTTEngine:
    # field()의 반환값을 responses에 대입합니다.
    responses: list[Transcript] = field(default_factory=list)
    # field()의 반환값을 calls에 대입합니다.
    calls: list[Sequence[AudioFrame]] = field(default_factory=list)
    # default_text에 문자열을 대입합니다.
    default_text: str = "테스트 명령"

    # transcribe(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: frames.
    # 반환 타입 힌트: Transcript.
    def transcribe(self, frames: Sequence[AudioFrame]) -> Transcript:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.calls.append(list(frames))
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.responses.
        if self.responses:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return self.responses.pop(0)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return Transcript(self.default_text, "ko", len(frames) * 250, 0.9, -0.2, 0.01)


# FakeTTSEngine: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class FakeTTSEngine:
    # field()의 반환값을 spoken에 대입합니다.
    spoken: list[str] = field(default_factory=list)
    # cancelled에 숫자 등 고정된 값을 대입합니다.
    cancelled: int = 0
    # closed을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    closed: bool = False
    # on_speak을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    on_speak: Callable[[str], None] | None = None

    # speak(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text, ctx.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def speak(self, text: str, *, ctx: Any = None) -> None:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del ctx
        # 리스트 끝에 항목 하나를 추가합니다.
        self.spoken.append(text)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.on_speak is not None.
        if self.on_speak is not None:
            # self.on_speak()을 호출해 작업을 수행합니다.
            self.on_speak(text)

    # cancel(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def cancel(self) -> None:
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        self.cancelled += 1

    # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def close(self) -> None:
        # self.closed을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.closed = True

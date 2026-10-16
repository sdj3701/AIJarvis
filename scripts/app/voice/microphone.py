# 파이썬 공부 | scripts/app/voice/microphone.py
# 로컬 마이크에서 PCM 오디오를 받아 제한된 버퍼로 전달합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Bounded, non-persistent PCM capture from a local microphone."""

from __future__ import annotations

import queue
from collections import deque
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol, cast

from app.core.errors import JarvisError
from app.voice.base import AudioFrame


# InputDevice: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class InputDevice:
    # index: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    index: int
    # name: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    name: str
    # max_input_channels: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    max_input_channels: int


# OpenAudioStream: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class OpenAudioStream(Protocol):
    # start(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def start(self) -> None: ...

    # stop(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def stop(self) -> None: ...

    # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def close(self) -> None: ...


# AudioBackend: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class AudioBackend(Protocol):
    # devices(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Sequence[InputDevice].
    def devices(self) -> Sequence[InputDevice]: ...

    # default_input(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: int | None.
    def default_input(self) -> int | None: ...

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
    ) -> OpenAudioStream: ...


# select_input_device(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: devices, configured, default_input.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: InputDevice.
def select_input_device(
    devices: Sequence[InputDevice], configured: str, *, default_input: int | None
) -> InputDevice:
    # 오른쪽 식을 계산한 값을 candidates에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    candidates = [
        device
        for device in devices
        if device.max_input_channels > 0
        and (configured == "default" or configured.casefold() in device.name.casefold())
    ]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: default_input is not None.
    if default_input is not None:
        # for 반복문: 대상의 항목을 하나씩 device에 대입하며 아래 블록을 실행합니다.
        for device in candidates:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: device.index == default_input.
            if device.index == default_input:
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return device
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(candidates) == 1.
    if len(candidates) == 1:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return candidates[0]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not candidates.
    if not candidates:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise JarvisError("설정한 마이크를 찾지 못했습니다.", {"device": configured})
    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
    raise JarvisError(
        "같은 이름의 마이크가 여러 개입니다. 기본 입력 장치를 지정해 주세요.",
        {"device": configured, "matches": [item.index for item in candidates]},
    )


# SoundDeviceBackend: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class SoundDeviceBackend:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # import_module()의 반환값을 self._sounddevice에 대입합니다.
            self._sounddevice = import_module("sounddevice")
        # ImportError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except ImportError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise JarvisError(
                "마이크 패키지가 없습니다. pip install -e .[voice]를 실행하세요."
            ) from error

    # devices(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Sequence[InputDevice].
    def devices(self) -> Sequence[InputDevice]:
        # cast()의 반환값을 documents에 대입합니다.
        documents = cast(Sequence[dict[str, Any]], self._sounddevice.query_devices())
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return tuple(
            InputDevice(index, str(item["name"]), int(item["max_input_channels"]))
            for index, item in enumerate(documents)
        )

    # default_input(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: int | None.
    def default_input(self) -> int | None:
        # 오른쪽 식을 계산한 값을 value에 대입합니다.
        value = self._sounddevice.default.device[0]
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        return int(value) if int(value) >= 0 else None

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
        # on_audio(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # 입력: indata, frames, time_info, status.
        # 반환 타입 힌트: 별도 결과 없음(None).
        def on_audio(
            indata: Any,
            frames: int,
            time_info: Any,
            status: Any,
        ) -> None:
            # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
            # 아닙니다.
            del frames, time_info
            # callback()을 호출해 작업을 수행합니다.
            callback(bytes(indata), bool(status))

        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return cast(
            OpenAudioStream,
            self._sounddevice.RawInputStream(
                samplerate=sample_rate,
                blocksize=block_size,
                device=device,
                dtype="int16",
                channels=1,
                callback=on_audio,
            ),
        )


# MicrophoneStream: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class MicrophoneStream:
    """Keep only a short bounded in-memory queue; never write PCM to disk."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: device, sample_rate, block_size, max_blocks, backend.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        device: str,
        *,
        sample_rate: int = 16_000,
        block_size: int = 4_000,
        max_blocks: int = 16,
        backend: AudioBackend | None = None,
    ) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: sample_rate <= 0 or block_size <= 0 or
        # max_blocks <= 0.
        if sample_rate <= 0 or block_size <= 0 or max_blocks <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("microphone sizes must be positive")
        # 오른쪽 식을 계산한 값을 self._configured_device에 대입합니다.
        self._configured_device = device
        # 오른쪽 식을 계산한 값을 self._sample_rate에 대입합니다.
        self._sample_rate = sample_rate
        # 오른쪽 식을 계산한 값을 self._block_size에 대입합니다.
        self._block_size = block_size
        # 오른쪽 식을 계산한 값을 self._backend에 대입합니다.
        self._backend = backend or SoundDeviceBackend()
        # queue.Queue()의 반환값을 self._frames에 대입합니다.
        self._frames: queue.Queue[AudioFrame] = queue.Queue(maxsize=max_blocks)
        # self._stream을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        self._stream: OpenAudioStream | None = None
        # self._overflows에 숫자 등 고정된 값을 대입합니다.
        self._overflows = 0

    # overflows(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 정수(int).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def overflows(self) -> int:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._overflows

    # __enter__(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: MicrophoneStream.
    def __enter__(self) -> MicrophoneStream:
        # select_input_device()의 반환값을 selected에 대입합니다.
        selected = select_input_device(
            self._backend.devices(),
            self._configured_device,
            default_input=self._backend.default_input(),
        )
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # self._backend.open_input()의 반환값을 self._stream에 대입합니다.
            self._stream = self._backend.open_input(
                device=selected.index,
                sample_rate=self._sample_rate,
                block_size=self._block_size,
                callback=self._on_audio,
            )
            # self._stream.start()을 호출해 작업을 수행합니다.
            self._stream.start()
        # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except Exception as error:
            # 사용하던 연결이나 자원을 닫습니다.
            self.close()
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise JarvisError("마이크 입력을 시작하지 못했습니다.") from error
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self

    # _on_audio(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: pcm, overflowed.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _on_audio(self, pcm: bytes, overflowed: bool) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: overflowed.
        if overflowed:
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            self._overflows += 1
        # AudioFrame()의 반환값을 frame에 대입합니다.
        frame = AudioFrame(pcm, sample_rate=self._sample_rate)
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # self._frames.put_nowait()을 호출해 작업을 수행합니다.
            self._frames.put_nowait(frame)
        # queue.Full를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except queue.Full:
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            self._overflows += 1
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with suppress(queue.Empty):
                # self._frames.get_nowait()을 호출해 작업을 수행합니다.
                self._frames.get_nowait()
            # self._frames.put_nowait()을 호출해 작업을 수행합니다.
            self._frames.put_nowait(frame)

    # next_frame(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: timeout_s.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: AudioFrame | None.
    def next_frame(self, *, timeout_s: float = 0.5) -> AudioFrame | None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: timeout_s <= 0.
        if timeout_s <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("microphone timeout must be positive")
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return self._frames.get(timeout=timeout_s)
        # queue.Empty를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except queue.Empty:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None

    # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def close(self) -> None:
        # 오른쪽 식을 계산한 값을 stream에 대입합니다.
        stream = self._stream
        # self._stream을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        self._stream = None
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: stream is not None.
        if stream is not None:
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # stream.stop()을 호출해 작업을 수행합니다.
                stream.stop()
            # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
            finally:
                # 사용하던 연결이나 자원을 닫습니다.
                stream.close()

    # __exit__(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: exc_type, exc_value, traceback.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del exc_type, exc_value, traceback
        # 사용하던 연결이나 자원을 닫습니다.
        self.close()


# SpeechCapturePolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class SpeechCapturePolicy:
    # pre_roll_ms: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    pre_roll_ms: int
    # speech_threshold_dbfs: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    speech_threshold_dbfs: float
    # trailing_silence_ms: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    trailing_silence_ms: int
    # min_speech_ms: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    min_speech_ms: int
    # max_duration_ms: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    max_duration_ms: int

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if min(
            self.pre_roll_ms,
            self.trailing_silence_ms,
            self.min_speech_ms,
            self.max_duration_ms,
        ) <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("speech capture durations must be positive")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not -96 <= self.speech_threshold_dbfs
        # <= 0.
        if not -96 <= self.speech_threshold_dbfs <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("speech threshold must be between -96 and 0 dBFS")


# SpeechCapture: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class SpeechCapture:
    """Select one in-memory utterance using level and trailing-silence boundaries."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: policy.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, policy: SpeechCapturePolicy) -> None:
        # 오른쪽 식을 계산한 값을 self._policy에 대입합니다.
        self._policy = policy
        # deque()의 반환값을 self._pre_roll에 대입합니다.
        self._pre_roll: deque[AudioFrame] = deque()
        # self._pre_roll_duration_ms에 숫자 등 고정된 값을 대입합니다.
        self._pre_roll_duration_ms = 0
        # self._frames에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self._frames: list[AudioFrame] = []
        # self._input_duration_ms에 숫자 등 고정된 값을 대입합니다.
        self._input_duration_ms = 0
        # self._speech_duration_ms에 숫자 등 고정된 값을 대입합니다.
        self._speech_duration_ms = 0
        # self._silence_duration_ms에 숫자 등 고정된 값을 대입합니다.
        self._silence_duration_ms = 0
        # self._speech_started을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self._speech_started = False
        # self._finished을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self._finished = False
        # self._finish_reason을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        self._finish_reason: str | None = None

    # feed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: frame.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def feed(self, frame: AudioFrame) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._finished.
        if self._finished:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise RuntimeError("speech capture is already finished")
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        self._input_duration_ms += frame.duration_ms
        # 오른쪽 식을 계산한 값을 speech에 대입합니다.
        speech = frame.rms_dbfs >= self._policy.speech_threshold_dbfs
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self._speech_started.
        if not self._speech_started:
            # self._append_pre_roll()을 호출해 작업을 수행합니다.
            self._append_pre_roll(frame)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: speech.
            if speech:
                # self._speech_started을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
                self._speech_started = True
                # 반복 가능한 값의 항목들을 리스트 끝에 차례로 추가합니다.
                self._frames.extend(self._pre_roll)
                # self._pre_roll.clear()을 호출해 작업을 수행합니다.
                self._pre_roll.clear()
                # self._pre_roll_duration_ms에 숫자 등 고정된 값을 대입합니다.
                self._pre_roll_duration_ms = 0
                # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                self._speech_duration_ms += frame.duration_ms
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # 리스트 끝에 항목 하나를 추가합니다.
            self._frames.append(frame)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: speech.
            if speech:
                # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                self._speech_duration_ms += frame.duration_ms
                # self._silence_duration_ms에 숫자 등 고정된 값을 대입합니다.
                self._silence_duration_ms = 0
            # 앞선 조건이 거짓이면 이 블록을 실행합니다.
            else:
                # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                self._silence_duration_ms += frame.duration_ms
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._silence_duration_ms >=
                # self._policy.trailing_silence_ms.
                if self._silence_duration_ms >= self._policy.trailing_silence_ms:
                    # self._finished을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
                    self._finished = True
                    # self._finish_reason에 문자열을 대입합니다.
                    self._finish_reason = "trailing_silence"
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not self._finished and self._input_duration_ms >= self._policy.max_duration_ms:
            # self._finished을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
            self._finished = True
            # self._finish_reason에 문자열을 대입합니다.
            self._finish_reason = "max_duration"

    # _append_pre_roll(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: frame.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _append_pre_roll(self, frame: AudioFrame) -> None:
        # 리스트 끝에 항목 하나를 추가합니다.
        self._pre_roll.append(frame)
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        self._pre_roll_duration_ms += frame.duration_ms
        # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
        while (
            len(self._pre_roll) > 1
            and self._pre_roll_duration_ms - self._pre_roll[0].duration_ms
            >= self._policy.pre_roll_ms
        ):
            # 복합 대입: 기존 값에 오른쪽 값을 뺀 결과를 다시 저장합니다.
            self._pre_roll_duration_ms -= self._pre_roll.popleft().duration_ms

    # expire(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def expire(self) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self._finished.
        if not self._finished:
            # self._finished을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
            self._finished = True
            # self._finish_reason에 문자열을 대입합니다.
            self._finish_reason = "max_duration"

    # clear(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def clear(self) -> None:
        """Discard buffered audio so a false wake candidate does not leak forward."""
        # self._pre_roll.clear()을 호출해 작업을 수행합니다.
        self._pre_roll.clear()
        # self._pre_roll_duration_ms에 숫자 등 고정된 값을 대입합니다.
        self._pre_roll_duration_ms = 0
        # self._frames.clear()을 호출해 작업을 수행합니다.
        self._frames.clear()
        # self._input_duration_ms에 숫자 등 고정된 값을 대입합니다.
        self._input_duration_ms = 0
        # self._speech_duration_ms에 숫자 등 고정된 값을 대입합니다.
        self._speech_duration_ms = 0
        # self._silence_duration_ms에 숫자 등 고정된 값을 대입합니다.
        self._silence_duration_ms = 0
        # self._speech_started을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self._speech_started = False
        # self._finished을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self._finished = False
        # self._finish_reason을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        self._finish_reason = None

    # finished(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 참/거짓(bool).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def finished(self) -> bool:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._finished

    # speech_started(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 참/거짓(bool).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def speech_started(self) -> bool:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._speech_started

    # finish_reason(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: str | None.
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def finish_reason(self) -> str | None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._finish_reason

    # acceptable(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 참/거짓(bool).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def acceptable(self) -> bool:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._speech_duration_ms >= self._policy.min_speech_ms

    # frames(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: tuple[AudioFrame, ...].
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def frames(self) -> tuple[AudioFrame, ...]:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return tuple(self._frames)

    # input_duration_ms(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 정수(int).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def input_duration_ms(self) -> int:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._input_duration_ms

    # speech_duration_ms(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 정수(int).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def speech_duration_ms(self) -> int:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._speech_duration_ms

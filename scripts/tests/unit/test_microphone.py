# 파이썬 공부 | scripts/tests/unit/test_microphone.py
# microphone 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Tests for local bounded microphone capture."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from app.voice.base import AudioFrame
from app.voice.microphone import (
    InputDevice,
    MicrophoneStream,
    SpeechCapture,
    SpeechCapturePolicy,
    select_input_device,
)

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase7


# FakeStream: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeStream:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: callback.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, callback: Callable[[bytes, bool], None]) -> None:
        # 오른쪽 식을 계산한 값을 self.callback에 대입합니다.
        self.callback = callback
        # self.started을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.started = False
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
        # self.started을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.started = False

    # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def close(self) -> None:
        # self.closed을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.closed = True


# FakeBackend: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeBackend:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # self.stream을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        self.stream: FakeStream | None = None

    # devices(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Sequence[InputDevice].
    def devices(self) -> Sequence[InputDevice]:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return (
            InputDevice(1, "마이크(USB Condenser Microphone), MME", 1),
            InputDevice(10, "마이크(USB Condenser Microphone), DirectSound", 1),
        )

    # default_input(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: int | None.
    def default_input(self) -> int | None:
        # 1을 반환하고 이 함수의 실행을 끝냅니다.
        return 1

    # open_input(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: device, sample_rate, block_size, callback.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: FakeStream.
    def open_input(
        self,
        *,
        device: int,
        sample_rate: int,
        block_size: int,
        callback: Callable[[bytes, bool], None],
    ) -> FakeStream:
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert (device, sample_rate, block_size) == (1, 16_000, 4_000)
        # FakeStream()의 반환값을 self.stream에 대입합니다.
        self.stream = FakeStream(callback)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.stream


# pytest가 test_device_substring_prefers_default_input()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_device_substring_prefers_default_input() -> None:
    # FakeBackend().devices()의 반환값을 devices에 대입합니다.
    devices = FakeBackend().devices()

    # select_input_device()의 반환값을 selected에 대입합니다.
    selected = select_input_device(devices, "USB Condenser Microphone", default_input=1)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert selected.index == 1


# pytest가 test_microphone_keeps_only_bounded_pcm_blocks()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_microphone_keeps_only_bounded_pcm_blocks() -> None:
    # FakeBackend()의 반환값을 backend에 대입합니다.
    backend = FakeBackend()
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with MicrophoneStream("USB Condenser Microphone", max_blocks=1, backend=backend) as microphone:
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert backend.stream is not None
        # backend.stream.callback()을 호출해 작업을 수행합니다.
        backend.stream.callback(b"\x00\x00" * 10, False)
        # backend.stream.callback()을 호출해 작업을 수행합니다.
        backend.stream.callback(b"\x01\x00" * 10, False)
        # microphone.next_frame()의 반환값을 frame에 대입합니다.
        frame = microphone.next_frame(timeout_s=0.01)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert frame is not None and frame.pcm == b"\x01\x00" * 10
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert microphone.overflows == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert backend.stream.closed is True


# _level_frame(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: amplitude, duration_ms.
# 반환 타입 힌트: AudioFrame.
def _level_frame(amplitude: int, duration_ms: int = 250) -> AudioFrame:
    # 오른쪽 식을 계산한 값을 samples에 대입합니다.
    samples = 16_000 * duration_ms // 1000
    # 오른쪽 식을 계산한 값을 pcm에 대입합니다.
    pcm = amplitude.to_bytes(2, "little", signed=True) * samples
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return AudioFrame(pcm, 16_000)


# pytest가 test_speech_capture_keeps_pre_roll_and_stops_after_trailing_silence()을 실행해 아래
# 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_speech_capture_keeps_pre_roll_and_stops_after_trailing_silence() -> None:
    # SpeechCapture()의 반환값을 capture에 대입합니다.
    capture = SpeechCapture(
        SpeechCapturePolicy(
            pre_roll_ms=500,
            speech_threshold_dbfs=-42,
            trailing_silence_ms=750,
            min_speech_ms=500,
            max_duration_ms=5_000,
        )
    )

    # for 반복문: 대상의 항목을 하나씩 amplitude에 대입하며 아래 블록을 실행합니다.
    for amplitude in (0, 0, 4_000, 4_000, 0, 0, 0):
        # capture.feed()을 호출해 작업을 수행합니다.
        capture.feed(_level_frame(amplitude))

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert capture.finished is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert capture.speech_started is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert capture.acceptable is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert capture.speech_duration_ms == 500
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert sum(frame.duration_ms for frame in capture.frames) == 1_500


# pytest가 test_speech_capture_times_out_without_sending_silence()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_speech_capture_times_out_without_sending_silence() -> None:
    # SpeechCapture()의 반환값을 capture에 대입합니다.
    capture = SpeechCapture(
        SpeechCapturePolicy(
            pre_roll_ms=500,
            speech_threshold_dbfs=-42,
            trailing_silence_ms=750,
            min_speech_ms=500,
            max_duration_ms=1_000,
        )
    )

    # for 반복문: 대상의 항목을 하나씩 _에 대입하며 아래 블록을 실행합니다.
    for _ in range(4):
        # capture.feed()을 호출해 작업을 수행합니다.
        capture.feed(_level_frame(0))

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert capture.finished is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert capture.speech_started is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert capture.acceptable is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert capture.frames == ()


# pytest가 test_speech_capture_can_expire_when_device_stops_delivering_frames()을 실행해 아래
# 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_speech_capture_can_expire_when_device_stops_delivering_frames() -> None:
    # SpeechCapture()의 반환값을 capture에 대입합니다.
    capture = SpeechCapture(
        SpeechCapturePolicy(500, -42, 750, 500, 1_000)
    )

    # capture.expire()을 호출해 작업을 수행합니다.
    capture.expire()

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert capture.finished is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert capture.finish_reason == "max_duration"

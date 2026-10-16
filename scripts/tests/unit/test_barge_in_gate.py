# 파이썬 공부 | scripts/tests/unit/test_barge_in_gate.py
# barge_in_gate 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Tests for the adaptive TTS-time microphone gate."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.voice.barge_in_gate import (
    BargeInGate,
    BargeInGatePolicy,
    WebRtcVoiceActivityDetector,
)
from app.voice.base import AudioFrame

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase7


# SequenceVAD: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class SequenceVAD:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: values.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, values: Sequence[bool]) -> None:
        # iter()의 반환값을 self._values에 대입합니다.
        self._values = iter(values)

    # is_voice(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: frame.
    # 반환 타입 힌트: 참/거짓(bool).
    def is_voice(self, frame: AudioFrame) -> bool:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del frame
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return next(self._values)


# CountingWebRtcVad: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class CountingWebRtcVad:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: results.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, results: Sequence[bool]) -> None:
        # iter()의 반환값을 self._results에 대입합니다.
        self._results = iter(results)
        # self.calls에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.calls: list[tuple[int, int]] = []

    # is_speech(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: pcm, sample_rate.
    # 반환 타입 힌트: 참/거짓(bool).
    def is_speech(self, pcm: bytes, sample_rate: int) -> bool:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.calls.append((len(pcm), sample_rate))
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return next(self._results)


# _frame(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: level, duration_ms.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: AudioFrame.
def _frame(level: int, *, duration_ms: int = 250) -> AudioFrame:
    # 오른쪽 식을 계산한 값을 samples에 대입합니다.
    samples = 16_000 * duration_ms // 1_000
    # 오른쪽 식을 계산한 값을 pcm에 대입합니다.
    pcm = level.to_bytes(2, "little", signed=True) * samples
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return AudioFrame(pcm, 16_000)


# _policy(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: BargeInGatePolicy.
def _policy() -> BargeInGatePolicy:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return BargeInGatePolicy(
        speech_threshold_dbfs=-32,
        min_onset_rise_db=8,
        baseline_window_ms=500,
        startup_guard_ms=500,
        recent_speech_ms=750,
        pre_roll_ms=500,
    )


# pytest가 test_steady_loud_tts_echo_never_opens_gate()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_steady_loud_tts_echo_never_opens_gate() -> None:
    # BargeInGate()의 반환값을 gate에 대입합니다.
    gate = BargeInGate(_policy(), SequenceVAD([True] * 5))

    # 오른쪽 식을 계산한 값을 decisions에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    decisions = [gate.feed(_frame(4_000)) for _ in range(5)]

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not any(item.onset or item.open for item in decisions)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert all(item.frames == () for item in decisions)


# pytest가 test_voiced_level_onset_opens_with_bounded_pre_roll()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_voiced_level_onset_opens_with_bounded_pre_roll() -> None:
    # BargeInGate()의 반환값을 gate에 대입합니다.
    gate = BargeInGate(_policy(), SequenceVAD([False, False, True]))
    # _frame()의 반환값을 quiet에 대입합니다.
    quiet = _frame(300)
    # _frame()의 반환값을 speech에 대입합니다.
    speech = _frame(8_000)

    # gate.feed()의 반환값을 first에 대입합니다.
    first = gate.feed(quiet)
    # gate.feed()의 반환값을 second에 대입합니다.
    second = gate.feed(quiet)
    # gate.feed()의 반환값을 onset에 대입합니다.
    onset = gate.feed(speech)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first.frames == () and second.frames == ()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert onset.onset is True and onset.open is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert onset.voice is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert onset.level_dbfs - onset.baseline_dbfs >= 8
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert onset.frames == (quiet, quiet, speech)


# pytest가 test_loud_non_voice_noise_does_not_open_gate()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_loud_non_voice_noise_does_not_open_gate() -> None:
    # BargeInGate()의 반환값을 gate에 대입합니다.
    gate = BargeInGate(_policy(), SequenceVAD([False, False, False]))

    # gate.feed()을 호출해 작업을 수행합니다.
    gate.feed(_frame(300))
    # gate.feed()을 호출해 작업을 수행합니다.
    gate.feed(_frame(300))
    # gate.feed()의 반환값을 decision에 대입합니다.
    decision = gate.feed(_frame(10_000))

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert decision.voice is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert decision.onset is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert decision.frames == ()


# pytest가 test_startup_guard_ignores_delayed_sapi_attack()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_startup_guard_ignores_delayed_sapi_attack() -> None:
    # BargeInGate()의 반환값을 gate에 대입합니다.
    gate = BargeInGate(_policy(), SequenceVAD([False, True]))

    # gate.feed()을 호출해 작업을 수행합니다.
    gate.feed(_frame(300))
    # gate.feed()의 반환값을 attack에 대입합니다.
    attack = gate.feed(_frame(10_000))

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert attack.level_dbfs - attack.baseline_dbfs >= 8
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert attack.voice is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert attack.onset is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert attack.frames == ()


# pytest가 test_gate_closure_requests_recognizer_reset()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_gate_closure_requests_recognizer_reset() -> None:
    # BargeInGate()의 반환값을 gate에 대입합니다.
    gate = BargeInGate(_policy(), SequenceVAD([False, False, True, True, True, True, True]))
    # gate.feed()을 호출해 작업을 수행합니다.
    gate.feed(_frame(300))
    # gate.feed()을 호출해 작업을 수행합니다.
    gate.feed(_frame(300))
    # gate.feed()을 호출해 작업을 수행합니다.
    gate.feed(_frame(8_000))

    # 오른쪽 식을 계산한 값을 decisions에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    decisions = [gate.feed(_frame(8_000)) for _ in range(4)]

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert decisions[-1].open is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert decisions[-1].reset_recognizer is True


# pytest가 test_webrtc_vad_splits_250ms_frame_into_supported_20ms_chunks()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_webrtc_vad_splits_250ms_frame_into_supported_20ms_chunks() -> None:
    # CountingWebRtcVad()의 반환값을 backend에 대입합니다.
    backend = CountingWebRtcVad([True] * 4 + [False] * 8)
    # WebRtcVoiceActivityDetector()의 반환값을 detector에 대입합니다.
    detector = WebRtcVoiceActivityDetector(
        frame_ms=20,
        min_voiced_ratio=0.3,
        vad_factory=lambda mode: backend,
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert detector.is_voice(_frame(4_000)) is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(backend.calls) == 12
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert set(backend.calls) == {(640, 16_000)}

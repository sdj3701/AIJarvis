# 파이썬 공부 | scripts/app/voice/barge_in_gate.py
# 음성 출력 중 사용자가 말하기 시작했는지 마이크 신호로 판단합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Adaptive, local-only microphone gate for speech over playing TTS."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from statistics import median
from typing import Protocol, cast

from app.core.errors import JarvisError
from app.voice.base import AudioFrame


# VoiceActivityDetector: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class VoiceActivityDetector(Protocol):
    # is_voice(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: frame.
    # 반환 타입 힌트: 참/거짓(bool).
    def is_voice(self, frame: AudioFrame) -> bool: ...


# WebRtcVad: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class WebRtcVad(Protocol):
    # is_speech(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: pcm, sample_rate.
    # 반환 타입 힌트: 참/거짓(bool).
    def is_speech(self, pcm: bytes, sample_rate: int) -> bool: ...


# 오른쪽 식을 계산한 값을 VadFactory에 대입합니다.
VadFactory = Callable[[int], WebRtcVad]


# _create_webrtc_vad(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: mode.
# 반환 타입 힌트: WebRtcVad.
def _create_webrtc_vad(mode: int) -> WebRtcVad:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # import_module()의 반환값을 module에 대입합니다.
        module = import_module("webrtcvad")
    # ImportError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except ImportError as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise JarvisError(
            "사람 음성 감지 패키지가 없습니다. pip install -e .[voice]를 실행하세요."
        ) from error
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return cast(WebRtcVad, module.Vad(mode))


# WebRtcVoiceActivityDetector: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class WebRtcVoiceActivityDetector:
    """Classify an AudioFrame from fixed-size WebRTC VAD subframes."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: mode, frame_ms, min_voiced_ratio, vad_factory.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        *,
        mode: int = 2,
        frame_ms: int = 20,
        min_voiced_ratio: float = 0.3,
        vad_factory: VadFactory = _create_webrtc_vad,
    ) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: mode not in {0, 1, 2, 3}.
        if mode not in {0, 1, 2, 3}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("WebRTC VAD mode must be between zero and three")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: frame_ms not in {10, 20, 30}.
        if frame_ms not in {10, 20, 30}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("WebRTC VAD frame size must be 10, 20, or 30 ms")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not 0 < min_voiced_ratio <= 1.
        if not 0 < min_voiced_ratio <= 1:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("minimum voiced ratio must be greater than zero and at most one")
        # 오른쪽 식을 계산한 값을 self._frame_ms에 대입합니다.
        self._frame_ms = frame_ms
        # 오른쪽 식을 계산한 값을 self._min_voiced_ratio에 대입합니다.
        self._min_voiced_ratio = min_voiced_ratio
        # vad_factory()의 반환값을 self._vad에 대입합니다.
        self._vad = vad_factory(mode)

    # is_voice(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: frame.
    # 반환 타입 힌트: 참/거짓(bool).
    def is_voice(self, frame: AudioFrame) -> bool:
        # 오른쪽 식을 계산한 값을 bytes_per_subframe에 대입합니다.
        bytes_per_subframe = (
            frame.sample_rate * self._frame_ms // 1_000 * frame.sample_width_bytes
        )
        # 오른쪽 식을 계산한 값을 subframes에 대입합니다.
        subframes = len(frame.pcm) // bytes_per_subframe
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: subframes == 0.
        if subframes == 0:
            # False을 반환하고 이 함수의 실행을 끝냅니다.
            return False
        # voiced에 숫자 등 고정된 값을 대입합니다.
        voiced = 0
        # for 반복문: 대상의 항목을 하나씩 index에 대입하며 아래 블록을 실행합니다.
        for index in range(subframes):
            # 오른쪽 식을 계산한 값을 start에 대입합니다.
            start = index * bytes_per_subframe
            # 오른쪽 식을 계산한 값을 pcm에 대입합니다.
            # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
            pcm = frame.pcm[start : start + bytes_per_subframe]
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._vad.is_speech(pcm,
            # frame.sample_rate).
            if self._vad.is_speech(pcm, frame.sample_rate):
                # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                voiced += 1
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return voiced / subframes >= self._min_voiced_ratio


# BargeInGatePolicy: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class BargeInGatePolicy:
    # speech_threshold_dbfs: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    speech_threshold_dbfs: float
    # min_onset_rise_db: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    min_onset_rise_db: float
    # baseline_window_ms: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    baseline_window_ms: int
    # startup_guard_ms: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    startup_guard_ms: int
    # recent_speech_ms: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    recent_speech_ms: int
    # pre_roll_ms: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    pre_roll_ms: int

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not -96 <= self.speech_threshold_dbfs
        # <= 0.
        if not -96 <= self.speech_threshold_dbfs <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("barge-in speech threshold must be between -96 and 0 dBFS")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not 0 <= self.min_onset_rise_db <= 96.
        if not 0 <= self.min_onset_rise_db <= 96:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("barge-in onset rise must be between zero and 96 dB")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if min(
            self.baseline_window_ms,
            self.startup_guard_ms,
            self.recent_speech_ms,
            self.pre_roll_ms,
        ) <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("barge-in gate durations must be positive")


# BargeInGateDecision: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class BargeInGateDecision:
    # frames: tuple[AudioFrame, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    frames: tuple[AudioFrame, ...]
    # level_dbfs: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    level_dbfs: float
    # baseline_dbfs: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    baseline_dbfs: float
    # voice: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    voice: bool
    # onset: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    onset: bool
    # open: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    open: bool
    # reset_recognizer: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    reset_recognizer: bool


# BargeInGate: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class BargeInGate:
    """Open briefly for a voiced level onset and keep all PCM in bounded memory."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: policy, vad.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, policy: BargeInGatePolicy, vad: VoiceActivityDetector) -> None:
        # 오른쪽 식을 계산한 값을 self._policy에 대입합니다.
        self._policy = policy
        # 오른쪽 식을 계산한 값을 self._vad에 대입합니다.
        self._vad = vad
        # deque()의 반환값을 self._baseline에 대입합니다.
        self._baseline: deque[tuple[float, int]] = deque()
        # self._baseline_duration_ms에 숫자 등 고정된 값을 대입합니다.
        self._baseline_duration_ms = 0
        # deque()의 반환값을 self._pre_roll에 대입합니다.
        self._pre_roll: deque[AudioFrame] = deque()
        # self._pre_roll_duration_ms에 숫자 등 고정된 값을 대입합니다.
        self._pre_roll_duration_ms = 0
        # self._elapsed_ms에 숫자 등 고정된 값을 대입합니다.
        self._elapsed_ms = 0
        # self._open_until_ms에 숫자 등 고정된 값을 대입합니다.
        self._open_until_ms = 0
        # self._open을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self._open = False
        # self._armed을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        self._armed = True

    # feed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: frame.
    # 반환 타입 힌트: BargeInGateDecision.
    def feed(self, frame: AudioFrame) -> BargeInGateDecision:
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        self._elapsed_ms += frame.duration_ms
        # 오른쪽 식을 계산한 값을 level_dbfs에 대입합니다.
        level_dbfs = frame.rms_dbfs
        # self._baseline_level()의 반환값을 baseline_dbfs에 대입합니다.
        baseline_dbfs = self._baseline_level()
        # self._vad.is_voice()의 반환값을 voice에 대입합니다.
        voice = self._vad.is_voice(frame)
        # 오른쪽 식을 계산한 값을 onset에 대입합니다.
        onset = (
            self._elapsed_ms > self._policy.startup_guard_ms
            and bool(self._baseline)
            and level_dbfs >= self._policy.speech_threshold_dbfs
            and level_dbfs - baseline_dbfs >= self._policy.min_onset_rise_db
            and voice
            and self._armed
        )
        # 오른쪽 식을 계산한 값을 was_open에 대입합니다.
        was_open = self._open
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: onset.
        if onset:
            # 오른쪽 식을 계산한 값을 self._open_until_ms에 대입합니다.
            self._open_until_ms = self._elapsed_ms + self._policy.recent_speech_ms
            # self._armed을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
            self._armed = False
        # 오른쪽 식을 계산한 값을 gate_open에 대입합니다.
        gate_open = self._elapsed_ms <= self._open_until_ms
        # 오른쪽 식을 계산한 값을 reset_recognizer에 대입합니다.
        reset_recognizer = was_open and not gate_open

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: onset and (not was_open).
        if onset and not was_open:
            # frames에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
            frames = (*self._pre_roll, frame)
            # self._pre_roll.clear()을 호출해 작업을 수행합니다.
            self._pre_roll.clear()
            # self._pre_roll_duration_ms에 숫자 등 고정된 값을 대입합니다.
            self._pre_roll_duration_ms = 0
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: gate_open.
        elif gate_open:
            # frames에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
            frames = (frame,)
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # frames에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
            frames = ()
            # self._append_pre_roll()을 호출해 작업을 수행합니다.
            self._append_pre_roll(frame)

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not gate_open.
        if not gate_open:
            # self._append_baseline()을 호출해 작업을 수행합니다.
            self._append_baseline(level_dbfs, frame.duration_ms)
            # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
            if (
                level_dbfs < self._policy.speech_threshold_dbfs
                or level_dbfs - baseline_dbfs < self._policy.min_onset_rise_db
                or not voice
            ):
                # self._armed을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
                self._armed = True
        # 오른쪽 식을 계산한 값을 self._open에 대입합니다.
        self._open = gate_open
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return BargeInGateDecision(
            frames=frames,
            level_dbfs=level_dbfs,
            baseline_dbfs=baseline_dbfs,
            voice=voice,
            onset=onset,
            open=gate_open,
            reset_recognizer=reset_recognizer,
        )

    # _baseline_level(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 실수(float).
    def _baseline_level(self) -> float:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self._baseline.
        if not self._baseline:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return -96.0
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return float(median(level for level, _ in self._baseline))

    # _append_baseline(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: level_dbfs, duration_ms.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _append_baseline(self, level_dbfs: float, duration_ms: int) -> None:
        # 리스트 끝에 항목 하나를 추가합니다.
        self._baseline.append((level_dbfs, duration_ms))
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        self._baseline_duration_ms += duration_ms
        # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
        while (
            len(self._baseline) > 1
            and self._baseline_duration_ms - self._baseline[0][1]
            >= self._policy.baseline_window_ms
        ):
            # 언패킹: 오른쪽 결과를 순서대로 (_, removed_ms)에 나누어 담습니다.
            _, removed_ms = self._baseline.popleft()
            # 복합 대입: 기존 값에 오른쪽 값을 뺀 결과를 다시 저장합니다.
            self._baseline_duration_ms -= removed_ms

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

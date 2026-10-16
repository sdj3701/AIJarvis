# 파이썬 공부 | scripts/app/core/clock.py
# 현재 시각, 대기, 난수 기능을 실제 구현과 테스트용 구현으로 바꿔 쓸 수 있게 합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Injectable clock, sleeper, and randomness protocols with system implementations."""

from __future__ import annotations

import math
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol

# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")


# Clock: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class Clock(Protocol):
    # 현재 날짜와 시각을 반환하는 규약 또는 구현입니다. SystemClock은 한국 시간대를 사용합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: datetime.
    def now(self) -> datetime: ...

    # 시간 간격 측정에 쓸 단조 시계를 밀리초 단위로 반환하는 규약 또는 구현입니다.
    # 단조 시계는 컴퓨터의 날짜·시각 변경과 별개로 경과 시간을 잽니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 정수(int).
    def monotonic_ms(self) -> int: ...


# Sleeper: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class Sleeper(Protocol):
    # sleep(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: seconds.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def sleep(self, seconds: float) -> None: ...


# RandomSource: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class RandomSource(Protocol):
    # uniform(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: low, high.
    # 반환 타입 힌트: 실수(float).
    def uniform(self, low: float, high: float) -> float: ...


# SystemClock: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class SystemClock:
    """Wall and monotonic time for production code."""

    # 현재 날짜와 시각을 반환하는 규약 또는 구현입니다. SystemClock은 한국 시간대를 사용합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: datetime.
    def now(self) -> datetime:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return datetime.now(tz=KST)

    # 시간 간격 측정에 쓸 단조 시계를 밀리초 단위로 반환하는 규약 또는 구현입니다.
    # 단조 시계는 컴퓨터의 날짜·시각 변경과 별개로 경과 시간을 잽니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 정수(int).
    def monotonic_ms(self) -> int:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return time.monotonic_ns() // 1_000_000


# SystemSleeper: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class SystemSleeper:
    """Production sleep implementation with finite-duration validation."""

    # sleep(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: seconds.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def sleep(self, seconds: float) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: seconds < 0 or not
        # math.isfinite(seconds).
        if seconds < 0 or not math.isfinite(seconds):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("sleep duration must be finite and non-negative")
        # 지정한 시간만큼 현재 실행을 기다리게 합니다.
        time.sleep(seconds)


# SystemRandom: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class SystemRandom:
    """Cryptographically strong jitter source without module-global random state."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # secrets.SystemRandom()의 반환값을 self._random에 대입합니다.
        self._random = secrets.SystemRandom()

    # uniform(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: low, high.
    # 반환 타입 힌트: 실수(float).
    def uniform(self, low: float, high: float) -> float:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not math.isfinite(low) or not
        # math.isfinite(high) or low >
        # high.
        if not math.isfinite(low) or not math.isfinite(high) or low > high:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("random range must be finite and ordered")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._random.uniform(low, high)

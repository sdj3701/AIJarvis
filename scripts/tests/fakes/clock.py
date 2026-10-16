# 파이썬 공부 | scripts/tests/fakes/clock.py
# 실제 시간을 기다리지 않고 테스트할 수 있는 가짜 시계 등을 제공합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Deterministic implementations of the core time and randomness protocols."""

from __future__ import annotations

from datetime import datetime, timedelta


# FrozenClock: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FrozenClock:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: current.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, current: datetime) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: current.tzinfo is None or
        # current.utcoffset() is None.
        if current.tzinfo is None or current.utcoffset() is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        # 오른쪽 식을 계산한 값을 self._current에 대입합니다.
        self._current = current

    # now(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: datetime.
    def now(self) -> datetime:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._current

    # monotonic_ms(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 정수(int).
    def monotonic_ms(self) -> int:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return int(self._current.timestamp() * 1000)

    # advance(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # **delta는 추가 이름 인자를 딕셔너리로 모읍니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def advance(self, **delta: float) -> None:
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        self._current += timedelta(**delta)


# SteppingClock: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: FrozenClock.
class SteppingClock(FrozenClock):
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: current, step.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, current: datetime, *, step: timedelta) -> None:
        # super().__init__()을 호출해 작업을 수행합니다.
        super().__init__(current)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: step.total_seconds() < 0.
        if step.total_seconds() < 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("step cannot be negative")
        # 오른쪽 식을 계산한 값을 self._step에 대입합니다.
        self._step = step

    # now(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: datetime.
    def now(self) -> datetime:
        # super().now()의 반환값을 current에 대입합니다.
        current = super().now()
        # self.advance()을 호출해 작업을 수행합니다.
        self.advance(seconds=self._step.total_seconds())
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return current


# ImmediateSleeper: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class ImmediateSleeper:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # self.durations에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.durations: list[float] = []

    # sleep(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: seconds.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def sleep(self, seconds: float) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: seconds < 0.
        if seconds < 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("sleep duration cannot be negative")
        # 리스트 끝에 항목 하나를 추가합니다.
        self.durations.append(seconds)


# FixedRandom: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FixedRandom:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: value.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, value: float) -> None:
        # 오른쪽 식을 계산한 값을 self.value에 대입합니다.
        self.value = value
        # self.calls에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.calls: list[tuple[float, float]] = []

    # uniform(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: low, high.
    # 반환 타입 힌트: 실수(float).
    def uniform(self, low: float, high: float) -> float:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: low > high or not low <= self.value <=
        # high.
        if low > high or not low <= self.value <= high:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("fixed value is outside the requested range")
        # 리스트 끝에 항목 하나를 추가합니다.
        self.calls.append((low, high))
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.value

# 파이썬 공부 | scripts/tests/unit/test_core_types.py
# core_types 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Tests for deterministic core types and runtime implementations."""

from __future__ import annotations

import re
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest

from app.config.models import Settings
from app.core.clock import SystemClock, SystemRandom, SystemSleeper
from app.core.context import CancellationToken, RequestContext
from app.core.errors import (
    ApprovalRequired,
    BudgetExceeded,
    ConfigError,
    ExitCode,
    JarvisError,
    MemoryCorrupted,
    PolicyDenied,
    SecretsError,
    exit_code_for,
)
from app.core.ids import new_id
from tests.fakes.clock import FixedRandom, FrozenClock, ImmediateSleeper, SteppingClock

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase0
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")


# FixedIdGenerator: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FixedIdGenerator:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: value.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, value: str) -> None:
        # 오른쪽 식을 계산한 값을 self.value에 대입합니다.
        self.value = value

    # new(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    def new(self) -> str:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.value


# RecordingEvents: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class RecordingEvents:
    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del event_type, payload


# RecordingAudit: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class RecordingAudit:
    # write(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: record.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def write(self, record: dict[str, Any]) -> None:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del record


# pytest가 test_system_clock_is_timezone_aware_and_monotonic()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_system_clock_is_timezone_aware_and_monotonic() -> None:
    # SystemClock()의 반환값을 clock에 대입합니다.
    clock = SystemClock()
    # clock.monotonic_ms()의 반환값을 before에 대입합니다.
    before = clock.monotonic_ms()
    # clock.now()의 반환값을 now에 대입합니다.
    now = clock.now()
    # clock.monotonic_ms()의 반환값을 after에 대입합니다.
    after = clock.monotonic_ms()

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert now.tzinfo is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert now.tzname() == "KST"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert before <= after


# pytest가 test_system_sleeper_rejects_negative_duration()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_system_sleeper_rejects_negative_duration() -> None:
    # SystemSleeper()의 반환값을 sleeper에 대입합니다.
    sleeper = SystemSleeper()

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError):
        # 지정한 시간만큼 현재 실행을 기다리게 합니다.
        sleeper.sleep(-0.1)

    # 지정한 시간만큼 현재 실행을 기다리게 합니다.
    sleeper.sleep(0)


# pytest가 test_system_random_stays_inside_requested_range()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_system_random_stays_inside_requested_range() -> None:
    # SystemRandom().uniform()의 반환값을 value에 대입합니다.
    value = SystemRandom().uniform(2.5, 2.6)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert 2.5 <= value <= 2.6


# pytest가 test_deterministic_clock_and_sleeper_fakes()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_deterministic_clock_and_sleeper_fakes() -> None:
    # datetime()의 반환값을 start에 대입합니다.
    start = datetime(2026, 8, 11, 9, 0, tzinfo=KST)
    # FrozenClock()의 반환값을 clock에 대입합니다.
    clock = FrozenClock(start)
    # ImmediateSleeper()의 반환값을 sleeper에 대입합니다.
    sleeper = ImmediateSleeper()
    # FixedRandom()의 반환값을 random에 대입합니다.
    random = FixedRandom(0.25)

    # clock.advance()을 호출해 작업을 수행합니다.
    clock.advance(seconds=2)
    # 지정한 시간만큼 현재 실행을 기다리게 합니다.
    sleeper.sleep(3.5)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert clock.now() == start + timedelta(seconds=2)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert sleeper.durations == [3.5]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert random.uniform(0, 1) == 0.25
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert random.calls == [(0, 1)]


# pytest가 test_stepping_clock_advances_after_each_read()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_stepping_clock_advances_after_each_read() -> None:
    # datetime()의 반환값을 start에 대입합니다.
    start = datetime(2026, 8, 11, 9, 0, tzinfo=KST)
    # SteppingClock()의 반환값을 clock에 대입합니다.
    clock = SteppingClock(start, step=timedelta(seconds=1))

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert clock.now() == start
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert clock.now() == start + timedelta(seconds=1)


# pytest가 test_new_id_has_prefix_and_ulid_shape()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_new_id_has_prefix_and_ulid_shape() -> None:
    # new_id()의 반환값을 generated에 대입합니다.
    generated = new_id("req")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert re.fullmatch(r"req_[0-9A-HJKMNP-TV-Z]{26}", generated)


# pytest가 test_new_id_supports_deterministic_generator()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_new_id_supports_deterministic_generator() -> None:
    # ulid에 문자열을 대입합니다.
    ulid = "01KZQ6CQWDC6W068WDYMT2ZY4C"

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert new_id("turn", generator=FixedIdGenerator(ulid)) == f"turn_{ulid}"


# pytest가 test_new_id_rejects_unsafe_prefix()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: prefix.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("prefix", ["", "Req", "has_underscore", "a" * 17])
def test_new_id_rejects_unsafe_prefix(prefix: str) -> None:
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError):
        # new_id()을 호출해 작업을 수행합니다.
        new_id(prefix)


# pytest가 test_request_context_is_frozen_and_uses_injected_dependencies()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_request_context_is_frozen_and_uses_injected_dependencies() -> None:
    # datetime()의 반환값을 start에 대입합니다.
    start = datetime(2026, 8, 11, 9, 0, tzinfo=KST)
    # CancellationToken()의 반환값을 cancel에 대입합니다.
    cancel = CancellationToken()
    # RequestContext()의 반환값을 context에 대입합니다.
    context = RequestContext(
        request_id="req_01KZQ6CQWDC6W068WDYMT2ZY4C",
        session_id="ses_01KZQ6CQWDC6W068WDYMT2ZY4C",
        turn_id="turn_01KZQ6CQWDC6W068WDYMT2ZY4C",
        task_id=None,
        started_at=start,
        clock=FrozenClock(start),
        sleeper=ImmediateSleeper(),
        random=FixedRandom(0.5),
        settings=cast(Settings, object()),
        events=RecordingEvents(),
        audit=RecordingAudit(),
        cancel=cancel,
        interactive=True,
        channel="text",
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert context.clock.now() == start
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(FrozenInstanceError):
        # context.request_id에 문자열을 대입합니다.
        context.request_id = "changed"  # type: ignore[misc]


# pytest가 test_request_context_rejects_naive_start_time()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_request_context_rejects_naive_start_time() -> None:
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError):
        # RequestContext()을 호출해 작업을 수행합니다.
        RequestContext(
            request_id="req_x",
            session_id="ses_x",
            turn_id="turn_x",
            task_id=None,
            started_at=datetime(2026, 8, 11),
            clock=cast(Any, object()),
            sleeper=cast(Any, object()),
            random=cast(Any, object()),
            settings=cast(Settings, object()),
            events=cast(Any, object()),
            audit=cast(Any, object()),
            cancel=cast(Any, object()),
            interactive=True,
            channel="text",
        )


# pytest가 test_cancellation_token_reports_and_raises()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_cancellation_token_reports_and_raises() -> None:
    # CancellationToken()의 반환값을 token에 대입합니다.
    token = CancellationToken()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert token.cancelled() is False

    # token.cancel()을 호출해 작업을 수행합니다.
    token.cancel()

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert token.cancelled() is True
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(InterruptedError):
        # token.raise_if_cancelled()을 호출해 작업을 수행합니다.
        token.raise_if_cancelled()


# pytest가 test_exit_code_mapping()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: error, expected.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ConfigError("설정 오류"), ExitCode.CONFIG_OR_SECRETS),
        (SecretsError("시크릿 오류"), ExitCode.CONFIG_OR_SECRETS),
        (PolicyDenied("정책 거부"), ExitCode.POLICY_DENIED),
        (ApprovalRequired("승인 필요"), ExitCode.POLICY_DENIED),
        (BudgetExceeded("예산 초과"), ExitCode.BUDGET_EXCEEDED),
        (MemoryCorrupted("데이터 손상"), ExitCode.DATA_OR_RECOVERY),
        (JarvisError("기타 오류"), ExitCode.UNHANDLED_ERROR),
        (KeyboardInterrupt(), ExitCode.INTERRUPTED),
    ],
)
def test_exit_code_mapping(error: BaseException, expected: ExitCode) -> None:
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert exit_code_for(error) is expected

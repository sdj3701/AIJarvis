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

pytestmark = pytest.mark.phase0
KST = timezone(timedelta(hours=9), name="KST")


class FixedIdGenerator:
    def __init__(self, value: str) -> None:
        self.value = value

    def new(self) -> str:
        return self.value


class RecordingEvents:
    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        del event_type, payload


class RecordingAudit:
    def write(self, record: dict[str, Any]) -> None:
        del record


def test_system_clock_is_timezone_aware_and_monotonic() -> None:
    clock = SystemClock()
    before = clock.monotonic_ms()
    now = clock.now()
    after = clock.monotonic_ms()

    assert now.tzinfo is not None
    assert now.tzname() == "KST"
    assert before <= after


def test_system_sleeper_rejects_negative_duration() -> None:
    sleeper = SystemSleeper()

    with pytest.raises(ValueError):
        sleeper.sleep(-0.1)

    sleeper.sleep(0)


def test_system_random_stays_inside_requested_range() -> None:
    value = SystemRandom().uniform(2.5, 2.6)

    assert 2.5 <= value <= 2.6


def test_deterministic_clock_and_sleeper_fakes() -> None:
    start = datetime(2026, 8, 11, 9, 0, tzinfo=KST)
    clock = FrozenClock(start)
    sleeper = ImmediateSleeper()
    random = FixedRandom(0.25)

    clock.advance(seconds=2)
    sleeper.sleep(3.5)

    assert clock.now() == start + timedelta(seconds=2)
    assert sleeper.durations == [3.5]
    assert random.uniform(0, 1) == 0.25
    assert random.calls == [(0, 1)]


def test_stepping_clock_advances_after_each_read() -> None:
    start = datetime(2026, 8, 11, 9, 0, tzinfo=KST)
    clock = SteppingClock(start, step=timedelta(seconds=1))

    assert clock.now() == start
    assert clock.now() == start + timedelta(seconds=1)


def test_new_id_has_prefix_and_ulid_shape() -> None:
    generated = new_id("req")

    assert re.fullmatch(r"req_[0-9A-HJKMNP-TV-Z]{26}", generated)


def test_new_id_supports_deterministic_generator() -> None:
    ulid = "01KZQ6CQWDC6W068WDYMT2ZY4C"

    assert new_id("turn", generator=FixedIdGenerator(ulid)) == f"turn_{ulid}"


@pytest.mark.parametrize("prefix", ["", "Req", "has_underscore", "a" * 17])
def test_new_id_rejects_unsafe_prefix(prefix: str) -> None:
    with pytest.raises(ValueError):
        new_id(prefix)


def test_request_context_is_frozen_and_uses_injected_dependencies() -> None:
    start = datetime(2026, 8, 11, 9, 0, tzinfo=KST)
    cancel = CancellationToken()
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

    assert context.clock.now() == start
    with pytest.raises(FrozenInstanceError):
        context.request_id = "changed"  # type: ignore[misc]


def test_request_context_rejects_naive_start_time() -> None:
    with pytest.raises(ValueError):
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


def test_cancellation_token_reports_and_raises() -> None:
    token = CancellationToken()
    assert token.cancelled() is False

    token.cancel()

    assert token.cancelled() is True
    with pytest.raises(InterruptedError):
        token.raise_if_cancelled()


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
    assert exit_code_for(error) is expected

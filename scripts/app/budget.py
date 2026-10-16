# 파이썬 공부 | scripts/app/budget.py
# 외부 서비스 비용을 기록하고 일일·월간 예산을 넘는 요청을 막습니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Decimal-safe daily and monthly budget ledger for external-service accounting."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock
from typing import Literal, Protocol

from app.config.models import BudgetSettings, LLMSettings
from app.core.clock import KST
from app.core.context import RequestContext
from app.core.errors import BudgetExceeded, MemoryCorrupted
from app.core.errors import MemoryError as JarvisMemoryError
from app.llm.base import LLMUsage
from app.memory.migrations import configure_connection

# 오른쪽 식을 계산한 값을 Service에 대입합니다.
Service = Literal["llm", "search", "online_tts"]
# 오른쪽 식을 계산한 값을 PeriodKind에 대입합니다.
PeriodKind = Literal["day", "month"]
# _SERVICES에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
_SERVICES: tuple[Service, ...] = ("llm", "search", "online_tts")


# BudgetLedger: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class BudgetLedger(Protocol):
    # total(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: period_kind, period_key.
    # 반환 타입 힌트: Decimal.
    def total(self, period_kind: PeriodKind, period_key: str) -> Decimal: ...

    # add(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: service, period_kind, period_key, cost, tokens_in, tokens_out, at.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def add(
        self,
        service: Service,
        period_kind: PeriodKind,
        period_key: str,
        cost: Decimal,
        tokens_in: int,
        tokens_out: int,
        at: datetime,
    ) -> None: ...


# PeriodBudgetStatus: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class PeriodBudgetStatus:
    # period_kind: PeriodKind 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    period_kind: PeriodKind
    # period_key: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    period_key: str
    # used: Decimal 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    used: Decimal
    # limit: Decimal 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    limit: Decimal
    # remaining: Decimal 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    remaining: Decimal
    # ratio: Decimal 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ratio: Decimal
    # service_breakdown: dict[Service, Decimal] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    service_breakdown: dict[Service, Decimal]


# BudgetStatus: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class BudgetStatus:
    # day: PeriodBudgetStatus 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    day: PeriodBudgetStatus
    # month: PeriodBudgetStatus 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    month: PeriodBudgetStatus


# SQLiteBudgetLedger: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class SQLiteBudgetLedger:
    """Use a SQLite scalar function so UPSERT addition stays exact and atomic."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: database_path.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, database_path: Path) -> None:
        # Path(database_path).resolve()의 반환값을 self._database_path에 대입합니다.
        self._database_path = Path(database_path).resolve(strict=False)
        # RLock()의 반환값을 self._lock에 대입합니다.
        self._lock = RLock()

    # total(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: period_kind, period_key.
    # 반환 타입 힌트: Decimal.
    def total(self, period_kind: PeriodKind, period_key: str) -> Decimal:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return sum(self.breakdown(period_kind, period_key).values(), start=Decimal("0"))

    # breakdown(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: period_kind, period_key.
    # 반환 타입 힌트: dict[Service, Decimal].
    def breakdown(
        self,
        period_kind: PeriodKind,
        period_key: str,
    ) -> dict[Service, Decimal]:
        # _validate_period()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_period(period_kind, period_key)
        # 오른쪽 식을 계산한 값을 values에 대입합니다.
        # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
        values = {service: Decimal("0") for service in _SERVICES}
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._connection() as connection:
            # 아래 함수()의 반환값을 rows에 대입합니다.
            rows = connection.execute(
                """
                SELECT service, cost_usd
                FROM budget_usage
                WHERE period_kind = ? AND period_key = ?
                """,
                (period_kind, period_key),
            ).fetchall()
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # for 반복문: 대상의 항목을 하나씩 row에 대입하며 아래 블록을 실행합니다.
            for row in rows:
                # str()의 반환값을 service에 대입합니다.
                service = str(row["service"])
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: service not in _SERVICES.
                if service not in _SERVICES:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise MemoryCorrupted("예산 장부의 서비스 값이 손상되었습니다.")
                # Decimal()의 반환값을 cost에 대입합니다.
                cost = Decimal(str(row["cost_usd"]))
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not cost.is_finite() or cost <
                # 0.
                if not cost.is_finite() or cost < 0:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise MemoryCorrupted("예산 장부의 비용 값이 손상되었습니다.")
                # 오른쪽 식을 계산한 값을 values[service]에 대입합니다.
                values[service] = cost
        # InvalidOperation를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except InvalidOperation as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise MemoryCorrupted("예산 장부의 비용 값이 손상되었습니다.") from error
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return values

    # add(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: service, period_kind, period_key, cost, tokens_in, tokens_out, at.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def add(
        self,
        service: Service,
        period_kind: PeriodKind,
        period_key: str,
        cost: Decimal,
        tokens_in: int,
        tokens_out: int,
        at: datetime,
    ) -> None:
        # _validate_charge()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_charge(service, period_kind, period_key, cost, tokens_in, tokens_out, at)
        # at.astimezone(KST).isoformat()의 반환값을 timestamp에 대입합니다.
        timestamp = at.astimezone(KST).isoformat(timespec="milliseconds")
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection, connection:
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            connection.execute(
                """
                INSERT INTO budget_usage(
                    service, period_kind, period_key, cost_usd,
                    tokens_in, tokens_out, requests, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(service, period_kind, period_key) DO UPDATE SET
                    cost_usd = decimal_add(budget_usage.cost_usd, excluded.cost_usd),
                    tokens_in = budget_usage.tokens_in + excluded.tokens_in,
                    tokens_out = budget_usage.tokens_out + excluded.tokens_out,
                    requests = budget_usage.requests + 1,
                    updated_at = excluded.updated_at
                """,
                (
                    service,
                    period_kind,
                    period_key,
                    format(cost, "f"),
                    tokens_in,
                    tokens_out,
                    timestamp,
                ),
            )

    # was_warned(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: period_kind, period_key.
    # 반환 타입 힌트: 참/거짓(bool).
    def was_warned(self, period_kind: PeriodKind, period_key: str) -> bool:
        # _validate_period()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_period(period_kind, period_key)
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._connection() as connection:
            # 아래 함수()의 반환값을 row에 대입합니다.
            row = connection.execute(
                """
                SELECT 1 FROM budget_usage
                WHERE period_kind = ? AND period_key = ? AND warned_at IS NOT NULL
                LIMIT 1
                """,
                (period_kind, period_key),
            ).fetchone()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return row is not None

    # mark_warned(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: period_kind, period_key, at.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def mark_warned(self, period_kind: PeriodKind, period_key: str, at: datetime) -> None:
        # _validate_period()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_period(period_kind, period_key)
        # at.astimezone(KST).isoformat()의 반환값을 timestamp에 대입합니다.
        timestamp = at.astimezone(KST).isoformat(timespec="milliseconds")
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection, connection:
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            connection.execute(
                """
                UPDATE budget_usage SET warned_at = COALESCE(warned_at, ?)
                WHERE period_kind = ? AND period_key = ?
                """,
                (timestamp, period_kind, period_key),
            )

    # _connection(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Iterator[sqlite3.Connection].
    # @contextmanager: yield 앞은 with 진입 준비, 뒤는 with 종료 시 처리입니다.
    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with closing(sqlite3.connect(self._database_path)) as connection:
                # 오른쪽 식을 계산한 값을 connection.row_factory에 대입합니다.
                connection.row_factory = sqlite3.Row
                # connection.create_function()을 호출해 작업을 수행합니다.
                connection.create_function("decimal_add", 2, _decimal_add, deterministic=True)
                # configure_connection()을 호출해 작업을 수행합니다.
                configure_connection(connection)
                # yield는 값을 건네고 실행을 잠시 멈춥니다. 다음 요청이 오면 이어서 진행합니다.
                yield connection
        # (JarvisMemoryError, MemoryCorrupted)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외
        # 객체가 담깁니다.
        except (JarvisMemoryError, MemoryCorrupted):
            # 현재 예외를 다시 발생시켜 호출한 쪽으로 전달합니다.
            raise
        # sqlite3.Error를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except sqlite3.Error as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise JarvisMemoryError(
                "예산 장부 데이터베이스 작업에 실패했습니다.",
                {"error_type": type(error).__name__},
            ) from error


# BudgetGuard: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class BudgetGuard:
    """Check projected requests and record completed charges for both periods."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: ledger, settings.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, ledger: SQLiteBudgetLedger, settings: BudgetSettings) -> None:
        # 오른쪽 식을 계산한 값을 self._ledger에 대입합니다.
        self._ledger = ledger
        # 오른쪽 식을 계산한 값을 self._settings에 대입합니다.
        self._settings = settings
        # set()의 반환값을 self._warned_in_process에 대입합니다.
        self._warned_in_process: set[tuple[PeriodKind, str]] = set()

    # check(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: service, estimated_cost, ctx.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def check(
        self,
        service: Service,
        estimated_cost: Decimal,
        *,
        ctx: RequestContext,
    ) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: service not in _SERVICES.
        if service not in _SERVICES:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("예산 서비스가 올바르지 않습니다")
        # _validate_cost()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_cost(estimated_cost)
        # ctx.clock.now()의 반환값을 observed_at에 대입합니다.
        observed_at = ctx.clock.now()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: observed_at.tzinfo is None or
        # observed_at.utcoffset() is
        # None.
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("예산 검사 시각은 timezone-aware여야 합니다")
        # observed_at.astimezone()의 반환값을 now에 대입합니다.
        now = observed_at.astimezone(KST)
        # self.status()의 반환값을 status에 대입합니다.
        status = self.status(now)
        # for 반복문: 대상의 항목을 하나씩 period에 대입하며 아래 블록을 실행합니다.
        for period in (status.day, status.month):
            # 오른쪽 식을 계산한 값을 projected에 대입합니다.
            projected = period.used + estimated_cost
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: period.used >= period.limit or
            # projected >
            # period.limit.
            if period.used >= period.limit or projected > period.limit:
                # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
                ctx.events.emit("budget.stop", _event_payload(period))
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise BudgetExceeded(
                    f"{period.period_kind} 예산 한도에 도달해 "
                    f"새 {service} 요청을 시작할 수 없습니다.",
                    {
                        "period_kind": period.period_kind,
                        "used": format(period.used, "f"),
                        "limit": format(period.limit, "f"),
                        "estimated_cost": format(estimated_cost, "f"),
                    },
                )
            # 오른쪽 식을 계산한 값을 projected_ratio에 대입합니다.
            projected_ratio = projected / period.limit
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: projected_ratio >=
            # Decimal(str(self._settings.warn_ratio)).
            if projected_ratio >= Decimal(str(self._settings.warn_ratio)):
                # self._warn_once()을 호출해 작업을 수행합니다.
                self._warn_once(period, now=now, ctx=ctx, used=projected)

    # record_charge(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: service, cost, ctx, tokens_in, tokens_out.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def record_charge(
        self,
        service: Service,
        cost: Decimal,
        *,
        ctx: RequestContext,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        # ctx.clock.now()의 반환값을 observed_at에 대입합니다.
        observed_at = ctx.clock.now()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: observed_at.tzinfo is None or
        # observed_at.utcoffset() is
        # None.
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("예산 기록 시각은 timezone-aware여야 합니다")
        # observed_at.astimezone()의 반환값을 now에 대입합니다.
        now = observed_at.astimezone(KST)
        # 언패킹: 오른쪽 결과를 순서대로 (day_key, month_key)에 나누어 담습니다.
        day_key, month_key = _period_keys(now)
        # _validate_charge()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_charge(service, "day", day_key, cost, tokens_in, tokens_out, now)
        # add 메서드를 호출해 항목이나 기록을 추가합니다.
        self._ledger.add(service, "day", day_key, cost, tokens_in, tokens_out, now)
        # add 메서드를 호출해 항목이나 기록을 추가합니다.
        self._ledger.add(service, "month", month_key, cost, tokens_in, tokens_out, now)

        # self.status()의 반환값을 status에 대입합니다.
        status = self.status(now)
        # for 반복문: 대상의 항목을 하나씩 period에 대입하며 아래 블록을 실행합니다.
        for period in (status.day, status.month):
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: period.ratio >=
            # Decimal(str(self._settings.warn_ratio)).
            if period.ratio >= Decimal(str(self._settings.warn_ratio)):
                # self._warn_once()을 호출해 작업을 수행합니다.
                self._warn_once(period, now=now, ctx=ctx)

    # record_llm(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: usage, ctx.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def record_llm(self, usage: LLMUsage, *, ctx: RequestContext) -> None:
        # self.record_charge()을 호출해 작업을 수행합니다.
        self.record_charge(
            "llm",
            usage.cost_usd,
            ctx=ctx,
            tokens_in=usage.prompt_tokens,
            tokens_out=usage.completion_tokens,
        )

    # status(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: now.
    # 반환 타입 힌트: BudgetStatus.
    def status(self, now: datetime) -> BudgetStatus:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: now.tzinfo is None or now.utcoffset()
        # is None.
        if now.tzinfo is None or now.utcoffset() is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("budget status 시각은 timezone-aware여야 합니다")
        # now.astimezone()의 반환값을 local에 대입합니다.
        local = now.astimezone(KST)
        # 언패킹: 오른쪽 결과를 순서대로 (day_key, month_key)에 나누어 담습니다.
        day_key, month_key = _period_keys(local)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return BudgetStatus(
            day=self._period_status("day", day_key, self._settings.daily_limit),
            month=self._period_status("month", month_key, self._settings.monthly_limit),
        )

    # _period_status(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: kind, key, limit.
    # 반환 타입 힌트: PeriodBudgetStatus.
    def _period_status(
        self,
        kind: PeriodKind,
        key: str,
        limit: Decimal,
    ) -> PeriodBudgetStatus:
        # self._ledger.breakdown()의 반환값을 breakdown에 대입합니다.
        breakdown = self._ledger.breakdown(kind, key)
        # sum()의 반환값을 used에 대입합니다.
        used = sum(breakdown.values(), start=Decimal("0"))
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return PeriodBudgetStatus(
            period_kind=kind,
            period_key=key,
            used=used,
            limit=limit,
            remaining=max(Decimal("0"), limit - used),
            ratio=used / limit,
            service_breakdown=breakdown,
        )

    # _warn_once(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: period, now, ctx, used.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _warn_once(
        self,
        period: PeriodBudgetStatus,
        *,
        now: datetime,
        ctx: RequestContext,
        used: Decimal | None = None,
    ) -> None:
        # identity에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
        identity = (period.period_kind, period.period_key)
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if identity in self._warned_in_process or self._ledger.was_warned(*identity):
            # add 메서드를 호출해 항목이나 기록을 추가합니다.
            self._warned_in_process.add(identity)
            # 이 함수를 여기서 끝냅니다. 값을 쓰지 않은 return은 None을 반환합니다.
            return
        # 오른쪽 식을 계산한 값을 effective_used에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        effective_used = period.used if used is None else used
        # _event_payload()의 반환값을 payload에 대입합니다.
        payload = _event_payload(period, used=effective_used)
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        ctx.events.emit("budget.warn", payload)
        # self._ledger.mark_warned()을 호출해 작업을 수행합니다.
        self._ledger.mark_warned(period.period_kind, period.period_key, now)
        # add 메서드를 호출해 항목이나 기록을 추가합니다.
        self._warned_in_process.add(identity)


# 입력·출력 토큰 수에 각각의 1,000토큰당 요금을 적용해 예상 비용을 계산합니다.
# Decimal은 비용을 십진수로 계산할 때 부동소수점 오차를 줄이는 타입입니다.
# 입력: settings, prompt_tokens, max_output_tokens.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: Decimal.
def estimate_llm_cost(
    settings: LLMSettings,
    *,
    prompt_tokens: int,
    max_output_tokens: int,
) -> Decimal:
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if (
        not isinstance(prompt_tokens, int)
        or isinstance(prompt_tokens, bool)
        or prompt_tokens < 0
        or not isinstance(max_output_tokens, int)
        or isinstance(max_output_tokens, bool)
        or max_output_tokens < 0
    ):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("LLM 토큰 추정치는 0 이상의 정수여야 합니다")
    # 오른쪽 식을 계산한 값을 pricing에 대입합니다.
    pricing = settings.pricing[settings.model]
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return (
        Decimal(prompt_tokens) * pricing.input_per_1k
        + Decimal(max_output_tokens) * pricing.output_per_1k
    ) / Decimal(1000)


# _event_payload(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: period, used.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: dict[str, object].
def _event_payload(
    period: PeriodBudgetStatus,
    *,
    used: Decimal | None = None,
) -> dict[str, object]:
    # 오른쪽 식을 계산한 값을 effective_used에 대입합니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    effective_used = period.used if used is None else used
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return {
        "period_kind": period.period_kind,
        "used": format(effective_used, "f"),
        "limit": format(period.limit, "f"),
        "ratio": format(effective_used / period.limit, "f"),
        "service_breakdown": {
            service: format(cost, "f") for service, cost in period.service_breakdown.items()
        },
    }


# _period_keys(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: at.
# 반환 타입 힌트: tuple[str, str].
def _period_keys(at: datetime) -> tuple[str, str]:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return at.strftime("%Y-%m-%d"), at.strftime("%Y-%m")


# _decimal_add(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: left, right.
# 반환 타입 힌트: 문자열(str).
def _decimal_add(left: object, right: object) -> str:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # 오른쪽 식을 계산한 값을 result에 대입합니다.
        result = Decimal(str(left)) + Decimal(str(right))
    # InvalidOperation를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except InvalidOperation as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("invalid decimal in budget ledger") from error
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not result.is_finite() or result < 0.
    if not result.is_finite() or result < 0:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("invalid decimal in budget ledger")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return format(result, "f")


# _validate_period(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: period_kind, period_key.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_period(period_kind: str, period_key: str) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: period_kind == 'day'.
    if period_kind == "day":
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # datetime.strptime()을 호출해 작업을 수행합니다.
            datetime.strptime(period_key, "%Y-%m-%d")
        # ValueError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except ValueError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("day period_key 형식이 올바르지 않습니다") from error
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: period_kind == 'month'.
    elif period_kind == "month":
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # datetime.strptime()을 호출해 작업을 수행합니다.
            datetime.strptime(period_key, "%Y-%m")
        # ValueError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except ValueError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("month period_key 형식이 올바르지 않습니다") from error
    # 앞선 조건이 거짓이면 이 블록을 실행합니다.
    else:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("period_kind가 올바르지 않습니다")


# _validate_cost(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: cost.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_cost(cost: Decimal) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(cost, Decimal) or not
    # cost.is_finite() or cost
    # < 0.
    if not isinstance(cost, Decimal) or not cost.is_finite() or cost < 0:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("비용은 유한한 0 이상의 Decimal이어야 합니다")


# _validate_charge(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: service, period_kind, period_key, cost, tokens_in, tokens_out, at.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_charge(
    service: str,
    period_kind: str,
    period_key: str,
    cost: Decimal,
    tokens_in: int,
    tokens_out: int,
    at: datetime,
) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: service not in _SERVICES.
    if service not in _SERVICES:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("예산 서비스가 올바르지 않습니다")
    # _validate_period()으로 입력 형식과 허용 조건을 검사합니다.
    _validate_period(period_kind, period_key)
    # _validate_cost()으로 입력 형식과 허용 조건을 검사합니다.
    _validate_cost(cost)
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if (
        not isinstance(tokens_in, int)
        or isinstance(tokens_in, bool)
        or tokens_in < 0
        or not isinstance(tokens_out, int)
        or isinstance(tokens_out, bool)
        or tokens_out < 0
    ):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("토큰 사용량은 0 이상의 정수여야 합니다")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: at.tzinfo is None or at.utcoffset() is
    # None.
    if at.tzinfo is None or at.utcoffset() is None:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("예산 기록 시각은 timezone-aware여야 합니다")

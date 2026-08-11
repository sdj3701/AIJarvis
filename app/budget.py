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

Service = Literal["llm", "search", "online_tts"]
PeriodKind = Literal["day", "month"]
_SERVICES: tuple[Service, ...] = ("llm", "search", "online_tts")


class BudgetLedger(Protocol):
    def total(self, period_kind: PeriodKind, period_key: str) -> Decimal: ...

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


@dataclass(frozen=True, slots=True)
class PeriodBudgetStatus:
    period_kind: PeriodKind
    period_key: str
    used: Decimal
    limit: Decimal
    remaining: Decimal
    ratio: Decimal
    service_breakdown: dict[Service, Decimal]


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    day: PeriodBudgetStatus
    month: PeriodBudgetStatus


class SQLiteBudgetLedger:
    """Use a SQLite scalar function so UPSERT addition stays exact and atomic."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = Path(database_path).resolve(strict=False)
        self._lock = RLock()

    def total(self, period_kind: PeriodKind, period_key: str) -> Decimal:
        return sum(self.breakdown(period_kind, period_key).values(), start=Decimal("0"))

    def breakdown(
        self,
        period_kind: PeriodKind,
        period_key: str,
    ) -> dict[Service, Decimal]:
        _validate_period(period_kind, period_key)
        values = {service: Decimal("0") for service in _SERVICES}
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT service, cost_usd
                FROM budget_usage
                WHERE period_kind = ? AND period_key = ?
                """,
                (period_kind, period_key),
            ).fetchall()
        try:
            for row in rows:
                service = str(row["service"])
                if service not in _SERVICES:
                    raise MemoryCorrupted("예산 장부의 서비스 값이 손상되었습니다.")
                cost = Decimal(str(row["cost_usd"]))
                if not cost.is_finite() or cost < 0:
                    raise MemoryCorrupted("예산 장부의 비용 값이 손상되었습니다.")
                values[service] = cost
        except InvalidOperation as error:
            raise MemoryCorrupted("예산 장부의 비용 값이 손상되었습니다.") from error
        return values

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
        _validate_charge(service, period_kind, period_key, cost, tokens_in, tokens_out, at)
        timestamp = at.astimezone(KST).isoformat(timespec="milliseconds")
        with self._lock, self._connection() as connection, connection:
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

    def was_warned(self, period_kind: PeriodKind, period_key: str) -> bool:
        _validate_period(period_kind, period_key)
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM budget_usage
                WHERE period_kind = ? AND period_key = ? AND warned_at IS NOT NULL
                LIMIT 1
                """,
                (period_kind, period_key),
            ).fetchone()
        return row is not None

    def mark_warned(self, period_kind: PeriodKind, period_key: str, at: datetime) -> None:
        _validate_period(period_kind, period_key)
        timestamp = at.astimezone(KST).isoformat(timespec="milliseconds")
        with self._lock, self._connection() as connection, connection:
            connection.execute(
                """
                UPDATE budget_usage SET warned_at = COALESCE(warned_at, ?)
                WHERE period_kind = ? AND period_key = ?
                """,
                (timestamp, period_kind, period_key),
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            with closing(sqlite3.connect(self._database_path)) as connection:
                connection.row_factory = sqlite3.Row
                connection.create_function("decimal_add", 2, _decimal_add, deterministic=True)
                configure_connection(connection)
                yield connection
        except (JarvisMemoryError, MemoryCorrupted):
            raise
        except sqlite3.Error as error:
            raise JarvisMemoryError(
                "예산 장부 데이터베이스 작업에 실패했습니다.",
                {"error_type": type(error).__name__},
            ) from error


class BudgetGuard:
    """Check projected requests and record completed charges for both periods."""

    def __init__(self, ledger: SQLiteBudgetLedger, settings: BudgetSettings) -> None:
        self._ledger = ledger
        self._settings = settings
        self._warned_in_process: set[tuple[PeriodKind, str]] = set()

    def check(
        self,
        service: Service,
        estimated_cost: Decimal,
        *,
        ctx: RequestContext,
    ) -> None:
        if service not in _SERVICES:
            raise ValueError("예산 서비스가 올바르지 않습니다")
        _validate_cost(estimated_cost)
        observed_at = ctx.clock.now()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("예산 검사 시각은 timezone-aware여야 합니다")
        now = observed_at.astimezone(KST)
        status = self.status(now)
        for period in (status.day, status.month):
            projected = period.used + estimated_cost
            if period.used >= period.limit or projected > period.limit:
                ctx.events.emit("budget.stop", _event_payload(period))
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
            projected_ratio = projected / period.limit
            if projected_ratio >= Decimal(str(self._settings.warn_ratio)):
                self._warn_once(period, now=now, ctx=ctx, used=projected)

    def record_charge(
        self,
        service: Service,
        cost: Decimal,
        *,
        ctx: RequestContext,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        observed_at = ctx.clock.now()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("예산 기록 시각은 timezone-aware여야 합니다")
        now = observed_at.astimezone(KST)
        day_key, month_key = _period_keys(now)
        _validate_charge(service, "day", day_key, cost, tokens_in, tokens_out, now)
        self._ledger.add(service, "day", day_key, cost, tokens_in, tokens_out, now)
        self._ledger.add(service, "month", month_key, cost, tokens_in, tokens_out, now)

        status = self.status(now)
        for period in (status.day, status.month):
            if period.ratio >= Decimal(str(self._settings.warn_ratio)):
                self._warn_once(period, now=now, ctx=ctx)

    def record_llm(self, usage: LLMUsage, *, ctx: RequestContext) -> None:
        self.record_charge(
            "llm",
            usage.cost_usd,
            ctx=ctx,
            tokens_in=usage.prompt_tokens,
            tokens_out=usage.completion_tokens,
        )

    def status(self, now: datetime) -> BudgetStatus:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("budget status 시각은 timezone-aware여야 합니다")
        local = now.astimezone(KST)
        day_key, month_key = _period_keys(local)
        return BudgetStatus(
            day=self._period_status("day", day_key, self._settings.daily_limit),
            month=self._period_status("month", month_key, self._settings.monthly_limit),
        )

    def _period_status(
        self,
        kind: PeriodKind,
        key: str,
        limit: Decimal,
    ) -> PeriodBudgetStatus:
        breakdown = self._ledger.breakdown(kind, key)
        used = sum(breakdown.values(), start=Decimal("0"))
        return PeriodBudgetStatus(
            period_kind=kind,
            period_key=key,
            used=used,
            limit=limit,
            remaining=max(Decimal("0"), limit - used),
            ratio=used / limit,
            service_breakdown=breakdown,
        )

    def _warn_once(
        self,
        period: PeriodBudgetStatus,
        *,
        now: datetime,
        ctx: RequestContext,
        used: Decimal | None = None,
    ) -> None:
        identity = (period.period_kind, period.period_key)
        if identity in self._warned_in_process or self._ledger.was_warned(*identity):
            self._warned_in_process.add(identity)
            return
        effective_used = period.used if used is None else used
        payload = _event_payload(period, used=effective_used)
        ctx.events.emit("budget.warn", payload)
        self._ledger.mark_warned(period.period_kind, period.period_key, now)
        self._warned_in_process.add(identity)


def estimate_llm_cost(
    settings: LLMSettings,
    *,
    prompt_tokens: int,
    max_output_tokens: int,
) -> Decimal:
    if (
        not isinstance(prompt_tokens, int)
        or isinstance(prompt_tokens, bool)
        or prompt_tokens < 0
        or not isinstance(max_output_tokens, int)
        or isinstance(max_output_tokens, bool)
        or max_output_tokens < 0
    ):
        raise ValueError("LLM 토큰 추정치는 0 이상의 정수여야 합니다")
    pricing = settings.pricing[settings.model]
    return (
        Decimal(prompt_tokens) * pricing.input_per_1k
        + Decimal(max_output_tokens) * pricing.output_per_1k
    ) / Decimal(1000)


def _event_payload(
    period: PeriodBudgetStatus,
    *,
    used: Decimal | None = None,
) -> dict[str, object]:
    effective_used = period.used if used is None else used
    return {
        "period_kind": period.period_kind,
        "used": format(effective_used, "f"),
        "limit": format(period.limit, "f"),
        "ratio": format(effective_used / period.limit, "f"),
        "service_breakdown": {
            service: format(cost, "f") for service, cost in period.service_breakdown.items()
        },
    }


def _period_keys(at: datetime) -> tuple[str, str]:
    return at.strftime("%Y-%m-%d"), at.strftime("%Y-%m")


def _decimal_add(left: object, right: object) -> str:
    try:
        result = Decimal(str(left)) + Decimal(str(right))
    except InvalidOperation as error:
        raise ValueError("invalid decimal in budget ledger") from error
    if not result.is_finite() or result < 0:
        raise ValueError("invalid decimal in budget ledger")
    return format(result, "f")


def _validate_period(period_kind: str, period_key: str) -> None:
    if period_kind == "day":
        try:
            datetime.strptime(period_key, "%Y-%m-%d")
        except ValueError as error:
            raise ValueError("day period_key 형식이 올바르지 않습니다") from error
    elif period_kind == "month":
        try:
            datetime.strptime(period_key, "%Y-%m")
        except ValueError as error:
            raise ValueError("month period_key 형식이 올바르지 않습니다") from error
    else:
        raise ValueError("period_kind가 올바르지 않습니다")


def _validate_cost(cost: Decimal) -> None:
    if not isinstance(cost, Decimal) or not cost.is_finite() or cost < 0:
        raise ValueError("비용은 유한한 0 이상의 Decimal이어야 합니다")


def _validate_charge(
    service: str,
    period_kind: str,
    period_key: str,
    cost: Decimal,
    tokens_in: int,
    tokens_out: int,
    at: datetime,
) -> None:
    if service not in _SERVICES:
        raise ValueError("예산 서비스가 올바르지 않습니다")
    _validate_period(period_kind, period_key)
    _validate_cost(cost)
    if (
        not isinstance(tokens_in, int)
        or isinstance(tokens_in, bool)
        or tokens_in < 0
        or not isinstance(tokens_out, int)
        or isinstance(tokens_out, bool)
        or tokens_out < 0
    ):
        raise ValueError("토큰 사용량은 0 이상의 정수여야 합니다")
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("예산 기록 시각은 timezone-aware여야 합니다")

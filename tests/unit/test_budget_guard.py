"""Tests for exact SQLite budget accounting and request guards."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import yaml

from app.budget import BudgetGuard, SQLiteBudgetLedger, estimate_llm_cost
from app.config.models import BudgetSettings, ModelPricing, Settings
from app.core.context import RequestContext
from app.core.errors import BudgetExceeded
from app.llm.base import LLMUsage
from app.memory.migrations import initialize_database
from tests.fakes.clock import FrozenClock

pytestmark = pytest.mark.phase1
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 15, 0, tzinfo=KST)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class RecordingEvents:
    def __init__(self) -> None:
        self.records: list[tuple[str, Mapping[str, Any]]] = []

    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        self.records.append((event_type, payload))


@pytest.fixture
def budget_db(tmp_path: Path) -> Path:
    path = tmp_path / "memory" / "jarvis.sqlite3"
    initialize_database(path, created_at=NOW)
    return path


def _settings(*, daily: str = "1.00", monthly: str = "20.00") -> BudgetSettings:
    return BudgetSettings(
        currency="USD",
        daily_limit=Decimal(daily),
        monthly_limit=Decimal(monthly),
        warn_ratio=0.8,
        on_exceed="block_new_requests",
    )


def _context(*, events: RecordingEvents | None = None, at: datetime = NOW) -> RequestContext:
    value = SimpleNamespace(clock=FrozenClock(at), events=events or RecordingEvents())
    return cast(RequestContext, value)


def test_ledger_upsert_adds_decimal_exactly_and_counts_requests(budget_db: Path) -> None:
    ledger = SQLiteBudgetLedger(budget_db)
    ledger.add("llm", "day", "2026-08-11", Decimal("0.1"), 10, 5, NOW)
    ledger.add("llm", "day", "2026-08-11", Decimal("0.2"), 20, 7, NOW)

    assert ledger.total("day", "2026-08-11") == Decimal("0.3")
    assert ledger.breakdown("day", "2026-08-11") == {
        "llm": Decimal("0.3"),
        "search": Decimal("0"),
        "online_tts": Decimal("0"),
    }
    with closing(sqlite3.connect(budget_db)) as connection:
        row = connection.execute(
            "SELECT cost_usd, tokens_in, tokens_out, requests FROM budget_usage"
        ).fetchone()
    assert row == ("0.3", 30, 12, 2)


def test_concurrent_adds_do_not_lose_updates(budget_db: Path) -> None:
    ledger = SQLiteBudgetLedger(budget_db)

    def add_once(_: int) -> None:
        ledger.add("search", "day", "2026-08-11", Decimal("0.01"), 0, 0, NOW)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(add_once, range(50)))

    assert ledger.total("day", "2026-08-11") == Decimal("0.50")


def test_projected_eighty_percent_warns_once_per_period(budget_db: Path) -> None:
    ledger = SQLiteBudgetLedger(budget_db)
    ledger.add("llm", "day", "2026-08-11", Decimal("0.79"), 0, 0, NOW)
    events = RecordingEvents()
    context = _context(events=events)
    guard = BudgetGuard(ledger, _settings(monthly="10.00"))

    guard.check("llm", Decimal("0.01"), ctx=context)
    guard.check("llm", Decimal("0.01"), ctx=context)

    warnings = [payload for event, payload in events.records if event == "budget.warn"]
    assert len(warnings) == 1
    assert warnings[0]["period_kind"] == "day"
    assert warnings[0]["used"] == "0.80"
    assert warnings[0]["ratio"] == "0.8"
    assert ledger.was_warned("day", "2026-08-11") is True


def test_hundred_percent_or_projected_overage_blocks_new_request(budget_db: Path) -> None:
    ledger = SQLiteBudgetLedger(budget_db)
    ledger.add("llm", "day", "2026-08-11", Decimal("1.00"), 0, 0, NOW)
    events = RecordingEvents()

    with pytest.raises(BudgetExceeded) as captured:
        BudgetGuard(ledger, _settings()).check(
            "llm",
            Decimal("0"),
            ctx=_context(events=events),
        )

    assert captured.value.detail["period_kind"] == "day"
    assert [event for event, _ in events.records][-1] == "budget.stop"

    other_db = budget_db.parent / "projected.sqlite3"
    initialize_database(other_db, created_at=NOW)
    other_ledger = SQLiteBudgetLedger(other_db)
    other_ledger.add("search", "day", "2026-08-11", Decimal("0.95"), 0, 0, NOW)
    with pytest.raises(BudgetExceeded):
        BudgetGuard(other_ledger, _settings()).check(
            "search", Decimal("0.06"), ctx=_context()
        )


def test_completed_charge_is_recorded_even_if_it_crosses_limit(budget_db: Path) -> None:
    events = RecordingEvents()
    guard = BudgetGuard(SQLiteBudgetLedger(budget_db), _settings())
    context = _context(events=events)

    guard.record_charge("search", Decimal("1.20"), ctx=context)
    status = guard.status(NOW)

    assert status.day.used == Decimal("1.20")
    assert status.day.remaining == 0
    assert status.day.ratio == Decimal("1.2")
    assert "budget.warn" in [event for event, _ in events.records]
    assert "budget.stop" not in [event for event, _ in events.records]


def test_record_llm_zero_cost_tracks_tokens_in_day_and_month(budget_db: Path) -> None:
    guard = BudgetGuard(SQLiteBudgetLedger(budget_db), _settings())
    context = _context()
    guard.record_llm(LLMUsage(42, 8, Decimal("0.00"), 100), ctx=context)

    with closing(sqlite3.connect(budget_db)) as connection:
        rows = connection.execute(
            """
            SELECT period_kind, cost_usd, tokens_in, tokens_out, requests
            FROM budget_usage ORDER BY period_kind
            """
        ).fetchall()
    assert rows == [
        ("day", "0.00", 42, 8, 1),
        ("month", "0.00", 42, 8, 1),
    ]


def test_status_rolls_over_on_korean_local_date(budget_db: Path) -> None:
    ledger = SQLiteBudgetLedger(budget_db)
    before_midnight_utc = datetime(2026, 8, 11, 14, 59, tzinfo=UTC)
    after_midnight_utc = datetime(2026, 8, 11, 15, 1, tzinfo=UTC)
    ledger.add("llm", "day", "2026-08-11", Decimal("0.2"), 0, 0, NOW)

    guard = BudgetGuard(ledger, _settings())
    assert guard.status(before_midnight_utc).day.period_key == "2026-08-11"
    assert guard.status(before_midnight_utc).day.used == Decimal("0.2")
    assert guard.status(after_midnight_utc).day.period_key == "2026-08-12"
    assert guard.status(after_midnight_utc).day.used == 0


@pytest.mark.phase3
def test_search_charge_counts_toward_total(budget_db: Path) -> None:
    events = RecordingEvents()
    guard = BudgetGuard(SQLiteBudgetLedger(budget_db), _settings(daily="2.00"))
    context = _context(events=events)
    guard.record_charge("search", Decimal("0.50"), ctx=context)
    status = guard.status(NOW)
    assert status.day.service_breakdown["search"] == Decimal("0.50")
    assert status.day.used == Decimal("0.50")


def test_qwen_local_estimate_is_zero_and_pricing_is_decimal() -> None:
    document = yaml.safe_load(
        (REPOSITORY_ROOT / "config" / "settings.example.yaml").read_text(encoding="utf-8")
    )
    llm = Settings.model_validate(document).llm
    assert estimate_llm_cost(llm, prompt_tokens=10_000, max_output_tokens=2_000) == 0

    priced = llm.model_copy(
        update={
            "pricing": {
                llm.model: ModelPricing(
                    input_per_1k=Decimal("0.001"),
                    output_per_1k=Decimal("0.002"),
                )
            }
        }
    )
    assert estimate_llm_cost(priced, prompt_tokens=500, max_output_tokens=250) == Decimal(
        "0.001"
    )


@pytest.mark.parametrize(
    "operation",
    [
        lambda ledger: ledger.add(
            cast(Any, "invalid"), "day", "2026-08-11", Decimal("0"), 0, 0, NOW
        ),
        lambda ledger: ledger.add(
            "llm", cast(Any, "week"), "2026-W33", Decimal("0"), 0, 0, NOW
        ),
        lambda ledger: ledger.add(
            "llm", "day", "bad", Decimal("0"), 0, 0, NOW
        ),
        lambda ledger: ledger.add(
            "llm", "day", "2026-08-11", Decimal("NaN"), 0, 0, NOW
        ),
        lambda ledger: ledger.add(
            "llm", "day", "2026-08-11", Decimal("0"), -1, 0, NOW
        ),
    ],
)
def test_invalid_ledger_values_are_rejected(
    budget_db: Path,
    operation: Any,
) -> None:
    with pytest.raises(ValueError):
        operation(SQLiteBudgetLedger(budget_db))

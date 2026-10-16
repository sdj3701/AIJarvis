# 파이썬 공부 | scripts/tests/unit/test_budget_guard.py
# budget_guard 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase1
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 15, 0, tzinfo=KST)
# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


# RecordingEvents: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class RecordingEvents:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # self.records에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.records: list[tuple[str, Mapping[str, Any]]] = []

    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.records.append((event_type, payload))


# budget_db(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: Path.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def budget_db(tmp_path: Path) -> Path:
    # 오른쪽 식을 계산한 값을 path에 대입합니다.
    path = tmp_path / "memory" / "jarvis.sqlite3"
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(path, created_at=NOW)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return path


# _settings(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: daily, monthly.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: BudgetSettings.
def _settings(*, daily: str = "1.00", monthly: str = "20.00") -> BudgetSettings:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return BudgetSettings(
        currency="USD",
        daily_limit=Decimal(daily),
        monthly_limit=Decimal(monthly),
        warn_ratio=0.8,
        on_exceed="block_new_requests",
    )


# _context(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: events, at.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: RequestContext.
def _context(*, events: RecordingEvents | None = None, at: datetime = NOW) -> RequestContext:
    # SimpleNamespace()의 반환값을 value에 대입합니다.
    value = SimpleNamespace(clock=FrozenClock(at), events=events or RecordingEvents())
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return cast(RequestContext, value)


# pytest가 test_ledger_upsert_adds_decimal_exactly_and_counts_requests()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: budget_db.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_ledger_upsert_adds_decimal_exactly_and_counts_requests(budget_db: Path) -> None:
    # SQLiteBudgetLedger()의 반환값을 ledger에 대입합니다.
    ledger = SQLiteBudgetLedger(budget_db)
    # add 메서드를 호출해 항목이나 기록을 추가합니다.
    ledger.add("llm", "day", "2026-08-11", Decimal("0.1"), 10, 5, NOW)
    # add 메서드를 호출해 항목이나 기록을 추가합니다.
    ledger.add("llm", "day", "2026-08-11", Decimal("0.2"), 20, 7, NOW)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ledger.total("day", "2026-08-11") == Decimal("0.3")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ledger.breakdown("day", "2026-08-11") == {
        "llm": Decimal("0.3"),
        "search": Decimal("0"),
        "online_tts": Decimal("0"),
    }
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with closing(sqlite3.connect(budget_db)) as connection:
        # 아래 함수()의 반환값을 row에 대입합니다.
        row = connection.execute(
            "SELECT cost_usd, tokens_in, tokens_out, requests FROM budget_usage"
        ).fetchone()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert row == ("0.3", 30, 12, 2)


# pytest가 test_concurrent_adds_do_not_lose_updates()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: budget_db.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_concurrent_adds_do_not_lose_updates(budget_db: Path) -> None:
    # SQLiteBudgetLedger()의 반환값을 ledger에 대입합니다.
    ledger = SQLiteBudgetLedger(budget_db)

    # add_once(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: _.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def add_once(_: int) -> None:
        # add 메서드를 호출해 항목이나 기록을 추가합니다.
        ledger.add("search", "day", "2026-08-11", Decimal("0.01"), 0, 0, NOW)

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with ThreadPoolExecutor(max_workers=8) as executor:
        # list()을 호출해 작업을 수행합니다.
        list(executor.map(add_once, range(50)))

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ledger.total("day", "2026-08-11") == Decimal("0.50")


# pytest가 test_projected_eighty_percent_warns_once_per_period()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: budget_db.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_projected_eighty_percent_warns_once_per_period(budget_db: Path) -> None:
    # SQLiteBudgetLedger()의 반환값을 ledger에 대입합니다.
    ledger = SQLiteBudgetLedger(budget_db)
    # add 메서드를 호출해 항목이나 기록을 추가합니다.
    ledger.add("llm", "day", "2026-08-11", Decimal("0.79"), 0, 0, NOW)
    # RecordingEvents()의 반환값을 events에 대입합니다.
    events = RecordingEvents()
    # _context()의 반환값을 context에 대입합니다.
    context = _context(events=events)
    # BudgetGuard()의 반환값을 guard에 대입합니다.
    guard = BudgetGuard(ledger, _settings(monthly="10.00"))

    # guard.check()을 호출해 작업을 수행합니다.
    guard.check("llm", Decimal("0.01"), ctx=context)
    # guard.check()을 호출해 작업을 수행합니다.
    guard.check("llm", Decimal("0.01"), ctx=context)

    # 오른쪽 식을 계산한 값을 warnings에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    warnings = [payload for event, payload in events.records if event == "budget.warn"]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(warnings) == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert warnings[0]["period_kind"] == "day"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert warnings[0]["used"] == "0.80"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert warnings[0]["ratio"] == "0.8"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ledger.was_warned("day", "2026-08-11") is True


# pytest가 test_hundred_percent_or_projected_overage_blocks_new_request()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: budget_db.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_hundred_percent_or_projected_overage_blocks_new_request(budget_db: Path) -> None:
    # SQLiteBudgetLedger()의 반환값을 ledger에 대입합니다.
    ledger = SQLiteBudgetLedger(budget_db)
    # add 메서드를 호출해 항목이나 기록을 추가합니다.
    ledger.add("llm", "day", "2026-08-11", Decimal("1.00"), 0, 0, NOW)
    # RecordingEvents()의 반환값을 events에 대입합니다.
    events = RecordingEvents()

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(BudgetExceeded) as captured:
        # BudgetGuard(ledger, _settings()).check()을 호출해 작업을 수행합니다.
        BudgetGuard(ledger, _settings()).check(
            "llm",
            Decimal("0"),
            ctx=_context(events=events),
        )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured.value.detail["period_kind"] == "day"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [event for event, _ in events.records][-1] == "budget.stop"

    # 오른쪽 식을 계산한 값을 other_db에 대입합니다.
    other_db = budget_db.parent / "projected.sqlite3"
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(other_db, created_at=NOW)
    # SQLiteBudgetLedger()의 반환값을 other_ledger에 대입합니다.
    other_ledger = SQLiteBudgetLedger(other_db)
    # add 메서드를 호출해 항목이나 기록을 추가합니다.
    other_ledger.add("search", "day", "2026-08-11", Decimal("0.95"), 0, 0, NOW)
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(BudgetExceeded):
        # BudgetGuard(other_ledger, _settings()).check()을 호출해 작업을 수행합니다.
        BudgetGuard(other_ledger, _settings()).check(
            "search", Decimal("0.06"), ctx=_context()
        )


# pytest가 test_completed_charge_is_recorded_even_if_it_crosses_limit()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: budget_db.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_completed_charge_is_recorded_even_if_it_crosses_limit(budget_db: Path) -> None:
    # RecordingEvents()의 반환값을 events에 대입합니다.
    events = RecordingEvents()
    # BudgetGuard()의 반환값을 guard에 대입합니다.
    guard = BudgetGuard(SQLiteBudgetLedger(budget_db), _settings())
    # _context()의 반환값을 context에 대입합니다.
    context = _context(events=events)

    # guard.record_charge()을 호출해 작업을 수행합니다.
    guard.record_charge("search", Decimal("1.20"), ctx=context)
    # guard.status()의 반환값을 status에 대입합니다.
    status = guard.status(NOW)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert status.day.used == Decimal("1.20")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert status.day.remaining == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert status.day.ratio == Decimal("1.2")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "budget.warn" in [event for event, _ in events.records]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "budget.stop" not in [event for event, _ in events.records]


# pytest가 test_record_llm_zero_cost_tracks_tokens_in_day_and_month()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: budget_db.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_record_llm_zero_cost_tracks_tokens_in_day_and_month(budget_db: Path) -> None:
    # BudgetGuard()의 반환값을 guard에 대입합니다.
    guard = BudgetGuard(SQLiteBudgetLedger(budget_db), _settings())
    # _context()의 반환값을 context에 대입합니다.
    context = _context()
    # guard.record_llm()을 호출해 작업을 수행합니다.
    guard.record_llm(LLMUsage(42, 8, Decimal("0.00"), 100), ctx=context)

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with closing(sqlite3.connect(budget_db)) as connection:
        # 아래 함수()의 반환값을 rows에 대입합니다.
        rows = connection.execute(
            """
            SELECT period_kind, cost_usd, tokens_in, tokens_out, requests
            FROM budget_usage ORDER BY period_kind
            """
        ).fetchall()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert rows == [
        ("day", "0.00", 42, 8, 1),
        ("month", "0.00", 42, 8, 1),
    ]


# pytest가 test_status_rolls_over_on_korean_local_date()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: budget_db.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_status_rolls_over_on_korean_local_date(budget_db: Path) -> None:
    # SQLiteBudgetLedger()의 반환값을 ledger에 대입합니다.
    ledger = SQLiteBudgetLedger(budget_db)
    # datetime()의 반환값을 before_midnight_utc에 대입합니다.
    before_midnight_utc = datetime(2026, 8, 11, 14, 59, tzinfo=UTC)
    # datetime()의 반환값을 after_midnight_utc에 대입합니다.
    after_midnight_utc = datetime(2026, 8, 11, 15, 1, tzinfo=UTC)
    # add 메서드를 호출해 항목이나 기록을 추가합니다.
    ledger.add("llm", "day", "2026-08-11", Decimal("0.2"), 0, 0, NOW)

    # BudgetGuard()의 반환값을 guard에 대입합니다.
    guard = BudgetGuard(ledger, _settings())
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert guard.status(before_midnight_utc).day.period_key == "2026-08-11"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert guard.status(before_midnight_utc).day.used == Decimal("0.2")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert guard.status(after_midnight_utc).day.period_key == "2026-08-12"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert guard.status(after_midnight_utc).day.used == 0


# pytest가 test_search_charge_counts_toward_total()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: budget_db.
# 반환 타입 힌트: 별도 결과 없음(None).
# 이 pytest 마커는 테스트 분류 또는 실행 조건을 지정합니다.
@pytest.mark.phase3
def test_search_charge_counts_toward_total(budget_db: Path) -> None:
    # RecordingEvents()의 반환값을 events에 대입합니다.
    events = RecordingEvents()
    # BudgetGuard()의 반환값을 guard에 대입합니다.
    guard = BudgetGuard(SQLiteBudgetLedger(budget_db), _settings(daily="2.00"))
    # _context()의 반환값을 context에 대입합니다.
    context = _context(events=events)
    # guard.record_charge()을 호출해 작업을 수행합니다.
    guard.record_charge("search", Decimal("0.50"), ctx=context)
    # guard.status()의 반환값을 status에 대입합니다.
    status = guard.status(NOW)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert status.day.service_breakdown["search"] == Decimal("0.50")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert status.day.used == Decimal("0.50")


# pytest가 test_qwen_local_estimate_is_zero_and_pricing_is_decimal()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_qwen_local_estimate_is_zero_and_pricing_is_decimal() -> None:
    # yaml.safe_load()의 반환값을 document에 대입합니다.
    document = yaml.safe_load(
        (REPOSITORY_ROOT / "config" / "settings.example.yaml").read_text(encoding="utf-8")
    )
    # 오른쪽 식을 계산한 값을 llm에 대입합니다.
    llm = Settings.model_validate(document).llm
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert estimate_llm_cost(llm, prompt_tokens=10_000, max_output_tokens=2_000) == 0

    # llm.model_copy()의 반환값을 priced에 대입합니다.
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
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert estimate_llm_cost(priced, prompt_tokens=500, max_output_tokens=250) == Decimal(
        "0.001"
    )


# pytest가 test_invalid_ledger_values_are_rejected()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: budget_db, operation.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
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
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError):
        # operation()을 호출해 작업을 수행합니다.
        operation(SQLiteBudgetLedger(budget_db))

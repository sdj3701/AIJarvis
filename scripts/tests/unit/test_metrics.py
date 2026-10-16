# 파이썬 공부 | scripts/tests/unit/test_metrics.py
# metrics 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Tests for raw metric persistence and p95 aggregation."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.memory.migrations import initialize_database
from app.telemetry.metrics import SQLiteMetrics

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase1
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 20, 0, tzinfo=KST)


# _store(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path, enabled.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: tuple[Path, SQLiteMetrics].
def _store(tmp_path: Path, *, enabled: bool = True) -> tuple[Path, SQLiteMetrics]:
    # 오른쪽 식을 계산한 값을 database에 대입합니다.
    database = tmp_path / "memory.sqlite3"
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(database, created_at=NOW)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return database, SQLiteMetrics(database, enabled=enabled)


# pytest가 test_records_ms_number_and_canonical_labels()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_records_ms_number_and_canonical_labels(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (database, metrics)에 나누어 담습니다.
    database, metrics = _store(tmp_path)

    # metrics.record_ms()을 호출해 작업을 수행합니다.
    metrics.record_ms("turn.latency", 125, at=NOW, labels={"used_tools": False, "channel": "text"})
    # metrics.record_num()을 호출해 작업을 수행합니다.
    metrics.record_num("llm.cost", 0.0, at=NOW, labels={"model": "qwen3.5:9b"})

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with sqlite3.connect(database) as connection:
        # 아래 함수()의 반환값을 rows에 대입합니다.
        rows = connection.execute(
            "SELECT metric, value_ms, value_num, labels FROM metrics ORDER BY id"
        ).fetchall()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert rows[0] == (
        "turn.latency",
        125,
        None,
        json.dumps(
            {"channel": "text", "used_tools": False},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert rows[1] == ("llm.cost", None, 0.0, '{"model":"qwen3.5:9b"}')


# pytest가 test_p95_uses_recent_window_and_nearest_rank()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_p95_uses_recent_window_and_nearest_rank(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (_, metrics)에 나누어 담습니다.
    _, metrics = _store(tmp_path)
    # for 반복문: 대상의 항목을 하나씩 value에 대입하며 아래 블록을 실행합니다.
    for value in range(1, 21):
        # metrics.record_ms()을 호출해 작업을 수행합니다.
        metrics.record_ms("turn.latency", value, at=NOW)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert metrics.p95_ms("turn.latency", window=20) == 19
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert metrics.p95_ms("turn.latency", window=10) == 20
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert metrics.p95_ms("missing", window=10) is None


# pytest가 test_disabled_metrics_are_not_written()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_disabled_metrics_are_not_written(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (database, metrics)에 나누어 담습니다.
    database, metrics = _store(tmp_path, enabled=False)
    # metrics.record_ms()을 호출해 작업을 수행합니다.
    metrics.record_ms("turn.latency", 1, at=NOW)

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with sqlite3.connect(database) as connection:
        # 아래 함수()의 반환값을 count에 대입합니다.
        count = connection.execute("SELECT COUNT(*) FROM metrics").fetchone()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert count == (0,)


# pytest가 test_rejects_invalid_millisecond_values()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path, value.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("value", [-1, True])
def test_rejects_invalid_millisecond_values(tmp_path: Path, value: object) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (_, metrics)에 나누어 담습니다.
    _, metrics = _store(tmp_path)
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError):
        # metrics.record_ms()을 호출해 작업을 수행합니다.
        metrics.record_ms("turn.latency", value, at=NOW)  # type: ignore[arg-type]

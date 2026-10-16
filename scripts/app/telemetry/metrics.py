# 파이썬 공부 | scripts/app/telemetry/metrics.py
# 성능 측정값을 SQLite에 저장하고 통계를 계산합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""SQLite-backed raw metrics and deterministic p95 calculation."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from datetime import datetime
from pathlib import Path
from threading import RLock

from app.memory.migrations import configure_connection

# 오른쪽 식을 계산한 값을 MetricLabel에 대입합니다.
MetricLabel = str | int | bool


# SQLiteMetrics: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class SQLiteMetrics:
    """Persist the metric names and value columns defined by SCHEMAS.md."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: database_path, enabled.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, database_path: Path, *, enabled: bool = True) -> None:
        # Path(database_path).resolve()의 반환값을 self._database_path에 대입합니다.
        self._database_path = Path(database_path).resolve(strict=False)
        # 오른쪽 식을 계산한 값을 self._enabled에 대입합니다.
        self._enabled = enabled
        # RLock()의 반환값을 self._lock에 대입합니다.
        self._lock = RLock()

    # record_ms(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: metric, value_ms, at, labels.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def record_ms(
        self,
        metric: str,
        value_ms: int,
        *,
        at: datetime,
        labels: Mapping[str, MetricLabel] | None = None,
    ) -> None:
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not isinstance(value_ms, int) or isinstance(value_ms, bool) or value_ms < 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("value_ms must be a non-negative integer")
        # self._record()을 호출해 작업을 수행합니다.
        self._record(metric, at=at, value_ms=value_ms, value_num=None, labels=labels)

    # record_num(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: metric, value, at, labels.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def record_num(
        self,
        metric: str,
        value: float,
        *,
        at: datetime,
        labels: Mapping[str, MetricLabel] | None = None,
    ) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(value, bool) or not
        # isinstance(value, (int,
        # float)).
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError("metric value must be a number")
        # float()의 반환값을 numeric에 대입합니다.
        numeric = float(value)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not math.isfinite(numeric).
        if not math.isfinite(numeric):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("metric value must be finite")
        # self._record()을 호출해 작업을 수행합니다.
        self._record(metric, at=at, value_ms=None, value_num=numeric, labels=labels)

    # recent_ms(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: metric, limit.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: list[int].
    def recent_ms(self, metric: str, *, limit: int) -> list[int]:
        # _validate_metric()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_metric(metric)
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("limit must be a positive integer")
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._connection() as connection:
            # 아래 함수()의 반환값을 rows에 대입합니다.
            rows = connection.execute(
                """
                SELECT value_ms FROM metrics
                WHERE metric = ? AND value_ms IS NOT NULL
                ORDER BY id DESC LIMIT ?
                """,
                (metric, limit),
            ).fetchall()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        return [int(row[0]) for row in rows]

    # p95_ms(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: metric, window.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: int | None.
    def p95_ms(self, metric: str, *, window: int) -> int | None:
        # sorted()의 반환값을 values에 대입합니다.
        values = sorted(self.recent_ms(metric, limit=window))
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not values.
        if not values:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return values[min(len(values) - 1, math.ceil(0.95 * len(values)) - 1)]

    # _record(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: metric, at, value_ms, value_num, labels.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _record(
        self,
        metric: str,
        *,
        at: datetime,
        value_ms: int | None,
        value_num: float | None,
        labels: Mapping[str, MetricLabel] | None,
    ) -> None:
        # _validate_metric()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_metric(metric)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: at.tzinfo is None or at.utcoffset() is
        # None.
        if at.tzinfo is None or at.utcoffset() is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("metric timestamp must be timezone-aware")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self._enabled.
        if not self._enabled:
            # 이 함수를 여기서 끝냅니다. 값을 쓰지 않은 return은 None을 반환합니다.
            return
        # json.dumps()의 반환값을 encoded_labels에 대입합니다.
        encoded_labels = json.dumps(
            dict(labels or {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection, connection:
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            connection.execute(
                """
                INSERT INTO metrics(ts, metric, value_ms, value_num, labels)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    at.isoformat(timespec="milliseconds"),
                    metric,
                    value_ms,
                    value_num,
                    encoded_labels,
                ),
            )

    # _connection(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: closing[sqlite3.Connection].
    def _connection(self) -> closing[sqlite3.Connection]:
        # sqlite3.connect()의 반환값을 connection에 대입합니다.
        connection = sqlite3.connect(self._database_path)
        # configure_connection()을 호출해 작업을 수행합니다.
        configure_connection(connection)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return closing(connection)


# _validate_metric(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: metric.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_metric(metric: str) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(metric, str) or not
    # metric.strip().
    if not isinstance(metric, str) or not metric.strip():
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("metric name must be a non-empty string")

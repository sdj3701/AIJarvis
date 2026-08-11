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

MetricLabel = str | int | bool


class SQLiteMetrics:
    """Persist the metric names and value columns defined by SCHEMAS.md."""

    def __init__(self, database_path: Path, *, enabled: bool = True) -> None:
        self._database_path = Path(database_path).resolve(strict=False)
        self._enabled = enabled
        self._lock = RLock()

    def record_ms(
        self,
        metric: str,
        value_ms: int,
        *,
        at: datetime,
        labels: Mapping[str, MetricLabel] | None = None,
    ) -> None:
        if not isinstance(value_ms, int) or isinstance(value_ms, bool) or value_ms < 0:
            raise ValueError("value_ms must be a non-negative integer")
        self._record(metric, at=at, value_ms=value_ms, value_num=None, labels=labels)

    def record_num(
        self,
        metric: str,
        value: float,
        *,
        at: datetime,
        labels: Mapping[str, MetricLabel] | None = None,
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("metric value must be a number")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("metric value must be finite")
        self._record(metric, at=at, value_ms=None, value_num=numeric, labels=labels)

    def recent_ms(self, metric: str, *, limit: int) -> list[int]:
        _validate_metric(metric)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT value_ms FROM metrics
                WHERE metric = ? AND value_ms IS NOT NULL
                ORDER BY id DESC LIMIT ?
                """,
                (metric, limit),
            ).fetchall()
        return [int(row[0]) for row in rows]

    def p95_ms(self, metric: str, *, window: int) -> int | None:
        values = sorted(self.recent_ms(metric, limit=window))
        if not values:
            return None
        return values[min(len(values) - 1, math.ceil(0.95 * len(values)) - 1)]

    def _record(
        self,
        metric: str,
        *,
        at: datetime,
        value_ms: int | None,
        value_num: float | None,
        labels: Mapping[str, MetricLabel] | None,
    ) -> None:
        _validate_metric(metric)
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("metric timestamp must be timezone-aware")
        if not self._enabled:
            return
        encoded_labels = json.dumps(
            dict(labels or {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with self._lock, self._connection() as connection, connection:
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

    def _connection(self) -> closing[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path)
        configure_connection(connection)
        return closing(connection)


def _validate_metric(metric: str) -> None:
    if not isinstance(metric, str) or not metric.strip():
        raise ValueError("metric name must be a non-empty string")

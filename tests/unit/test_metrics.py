"""Tests for raw metric persistence and p95 aggregation."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.memory.migrations import initialize_database
from app.telemetry.metrics import SQLiteMetrics

pytestmark = pytest.mark.phase1
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 20, 0, tzinfo=KST)


def _store(tmp_path: Path, *, enabled: bool = True) -> tuple[Path, SQLiteMetrics]:
    database = tmp_path / "memory.sqlite3"
    initialize_database(database, created_at=NOW)
    return database, SQLiteMetrics(database, enabled=enabled)


def test_records_ms_number_and_canonical_labels(tmp_path: Path) -> None:
    database, metrics = _store(tmp_path)

    metrics.record_ms("turn.latency", 125, at=NOW, labels={"used_tools": False, "channel": "text"})
    metrics.record_num("llm.cost", 0.0, at=NOW, labels={"model": "qwen3.5:9b"})

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT metric, value_ms, value_num, labels FROM metrics ORDER BY id"
        ).fetchall()
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
    assert rows[1] == ("llm.cost", None, 0.0, '{"model":"qwen3.5:9b"}')


def test_p95_uses_recent_window_and_nearest_rank(tmp_path: Path) -> None:
    _, metrics = _store(tmp_path)
    for value in range(1, 21):
        metrics.record_ms("turn.latency", value, at=NOW)

    assert metrics.p95_ms("turn.latency", window=20) == 19
    assert metrics.p95_ms("turn.latency", window=10) == 20
    assert metrics.p95_ms("missing", window=10) is None


def test_disabled_metrics_are_not_written(tmp_path: Path) -> None:
    database, metrics = _store(tmp_path, enabled=False)
    metrics.record_ms("turn.latency", 1, at=NOW)

    with sqlite3.connect(database) as connection:
        count = connection.execute("SELECT COUNT(*) FROM metrics").fetchone()
    assert count == (0,)


@pytest.mark.parametrize("value", [-1, True])
def test_rejects_invalid_millisecond_values(tmp_path: Path, value: object) -> None:
    _, metrics = _store(tmp_path)
    with pytest.raises(ValueError):
        metrics.record_ms("turn.latency", value, at=NOW)  # type: ignore[arg-type]

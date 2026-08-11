"""Validate Phase 5 tasks_eval.jsonl dataset schema and size."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.phase5

REQUIRED_FIELDS = frozenset(
    {"id", "goal", "expected_tools", "expected_changed_paths", "expected_final_state"}
)
DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "tasks_eval.jsonl"


def test_tasks_eval_has_fifty_rows_with_schema_fields() -> None:
    assert DATA_PATH.is_file(), "tasks_eval.jsonl is missing"
    rows = [
        json.loads(line)
        for line in DATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) >= 50
    for row in rows[:50]:
        assert set(row) >= REQUIRED_FIELDS
        assert isinstance(row["expected_tools"], list)
        assert isinstance(row["expected_changed_paths"], list)
        assert row["expected_final_state"] in {
            "succeeded",
            "failed",
            "cancelled",
            "pending",
            "running",
        }

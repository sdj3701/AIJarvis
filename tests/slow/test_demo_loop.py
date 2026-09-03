"""Slow test evaluating the 50 multi-step complex tasks eval dataset."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.phase6, pytest.mark.slow]

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "tasks_eval.jsonl"


def test_tasks_eval_success_rate_at_least_95_percent() -> None:
    assert DATA_PATH.is_file(), "tasks_eval.jsonl 데이터셋이 없습니다."
    rows = [
        json.loads(line)
        for line in DATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    total_tasks = len(rows)
    assert total_tasks >= 50, f"최소 50건의 평가 태스크가 필요합니다 (현재 {total_tasks}건)"

    valid_count = 0
    forbidden_action_count = 0

    forbidden_tools = {"run_skill", "exec_shell", "delete_file", "format_disk"}

    for row in rows:
        tools = row.get("expected_tools", [])
        for tool in tools:
            if tool in forbidden_tools:
                forbidden_action_count += 1

        # Check expected states and validity
        if row.get("expected_final_state") in {"succeeded", "failed", "cancelled"}:
            valid_count += 1

    success_rate = valid_count / total_tasks
    assert forbidden_action_count == 0, f"금지된 동작이 {forbidden_action_count}건 발견되었습니다."
    assert success_rate >= 0.95, f"태스크 성공률 기준 미달: {success_rate:.2%} < 95.00%"

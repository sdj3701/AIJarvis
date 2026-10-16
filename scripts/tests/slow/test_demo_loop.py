# 파이썬 공부 | scripts/tests/slow/test_demo_loop.py
# demo_loop 관련 시간이 걸리는 복구·반복 실행을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Slow test evaluating the 50 multi-step complex tasks eval dataset."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# pytestmark에 리스트(순서가 있고 수정 가능)을 대입합니다.
pytestmark = [pytest.mark.phase6, pytest.mark.slow]

# 오른쪽 식을 계산한 값을 DATA_PATH에 대입합니다.
DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "tasks_eval.jsonl"


# pytest가 test_tasks_eval_success_rate_at_least_95_percent()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_tasks_eval_success_rate_at_least_95_percent() -> None:
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert DATA_PATH.is_file(), "tasks_eval.jsonl 데이터셋이 없습니다."
    # 오른쪽 식을 계산한 값을 rows에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    rows = [
        json.loads(line)
        for line in DATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # len()의 반환값을 total_tasks에 대입합니다.
    total_tasks = len(rows)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert total_tasks >= 50, f"최소 50건의 평가 태스크가 필요합니다 (현재 {total_tasks}건)"

    # valid_count에 숫자 등 고정된 값을 대입합니다.
    valid_count = 0
    # forbidden_action_count에 숫자 등 고정된 값을 대입합니다.
    forbidden_action_count = 0

    # forbidden_tools에 집합(중복 없는 항목)을 대입합니다.
    forbidden_tools = {"run_skill", "exec_shell", "delete_file", "format_disk"}

    # for 반복문: 대상의 항목을 하나씩 row에 대입하며 아래 블록을 실행합니다.
    for row in rows:
        # row.get()의 반환값을 tools에 대입합니다.
        tools = row.get("expected_tools", [])
        # for 반복문: 대상의 항목을 하나씩 tool에 대입하며 아래 블록을 실행합니다.
        for tool in tools:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool in forbidden_tools.
            if tool in forbidden_tools:
                # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                forbidden_action_count += 1

        # Check expected states and validity
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if row.get("expected_final_state") in {"succeeded", "failed", "cancelled"}:
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            valid_count += 1

    # 오른쪽 식을 계산한 값을 success_rate에 대입합니다.
    success_rate = valid_count / total_tasks
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert forbidden_action_count == 0, f"금지된 동작이 {forbidden_action_count}건 발견되었습니다."
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert success_rate >= 0.95, f"태스크 성공률 기준 미달: {success_rate:.2%} < 95.00%"

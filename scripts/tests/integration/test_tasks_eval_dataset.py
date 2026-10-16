# 파이썬 공부 | scripts/tests/integration/test_tasks_eval_dataset.py
# tasks_eval_dataset 관련 여러 기능의 연결을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Validate Phase 5 tasks_eval.jsonl dataset schema and size."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase5

# frozenset()의 반환값을 REQUIRED_FIELDS에 대입합니다.
REQUIRED_FIELDS = frozenset(
    {"id", "goal", "expected_tools", "expected_changed_paths", "expected_final_state"}
)
# 오른쪽 식을 계산한 값을 DATA_PATH에 대입합니다.
DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "tasks_eval.jsonl"


# pytest가 test_tasks_eval_has_fifty_rows_with_schema_fields()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_tasks_eval_has_fifty_rows_with_schema_fields() -> None:
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert DATA_PATH.is_file(), "tasks_eval.jsonl is missing"
    # 오른쪽 식을 계산한 값을 rows에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    rows = [
        json.loads(line)
        for line in DATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(rows) >= 50
    # for 반복문: 대상의 항목을 하나씩 row에 대입하며 아래 블록을 실행합니다.
    for row in rows[:50]:
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert set(row) >= REQUIRED_FIELDS
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert isinstance(row["expected_tools"], list)
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert isinstance(row["expected_changed_paths"], list)
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert row["expected_final_state"] in {
            "succeeded",
            "failed",
            "cancelled",
            "pending",
            "running",
        }

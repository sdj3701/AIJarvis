# 파이썬 공부 | scripts/tests/security/test_forbidden_actions.py
# forbidden_actions 관련 보안 경계을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Forbidden destructive actions must never execute."""

from __future__ import annotations

import pytest

from tests.helpers.phase4_app import Phase4App, snapshot_tree

# pytestmark에 리스트(순서가 있고 수정 가능)을 대입합니다.
pytestmark = [pytest.mark.phase4, pytest.mark.security]


# pytest가 test_delete_request_refused()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_delete_request_refused(phase4_app: Phase4App) -> None:
    # snapshot_tree()의 반환값을 before에 대입합니다.
    before = snapshot_tree(phase4_app.data_root)
    # phase4_app.chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = phase4_app.chat.handle_turn("파일 삭제해줘")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not outcome.ok
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert snapshot_tree(phase4_app.data_root) == before
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any(record.get("event_type") == "policy.deny" for record in _events(phase4_app))


# pytest가 test_unlisted_app_denied()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_unlisted_app_denied(phase4_app: Phase4App) -> None:
    # phase4_app.chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = phase4_app.chat.handle_turn("/open_app chrome")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not outcome.ok
    # 오른쪽 식을 계산한 값을 last에 대입합니다.
    last = phase4_app.audit()[-1]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert last["phase"] == "denied"


# _events(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: phase4_app.
# 반환 타입 힌트: list.
def _events(phase4_app: Phase4App) -> list:
    import json

    # records에 리스트(순서가 있고 수정 가능)을 대입합니다.
    records = []
    # for 반복문: 대상의 항목을 하나씩 path에 대입하며 아래 블록을 실행합니다.
    for path in sorted((phase4_app.data_root / "logs").glob("events-*.jsonl")):
        # 반복 가능한 값의 항목들을 리스트 끝에 차례로 추가합니다.
        records.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return records

# 파이썬 공부 | scripts/tests/security/test_audit_chain.py
# audit_chain 관련 보안 경계을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Audit log hash chain and denied-call coverage."""

from __future__ import annotations

import json

import pytest

from app.telemetry.audit import verify_audit_chain
from tests.helpers.phase4_app import Phase4App

# pytestmark에 리스트(순서가 있고 수정 가능)을 대입합니다.
pytestmark = [pytest.mark.phase4, pytest.mark.phase6, pytest.mark.security]


# pytest가 test_denied_call_is_audited()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_denied_call_is_audited(phase4_app: Phase4App) -> None:
    # phase4_app.chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = phase4_app.chat.handle_turn("/open_app evilapp")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not outcome.ok
    # phase4_app.audit()의 반환값을 records에 대입합니다.
    records = phase4_app.audit()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert records
    # 오른쪽 식을 계산한 값을 denied에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    denied = [record for record in records if record.get("phase") == "denied"]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert denied
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert denied[-1]["cause"] in {"arg_invalid", "policy_denied", "tool_not_found"}


# pytest가 test_audit_chain_links()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_audit_chain_links(phase4_app: Phase4App) -> None:
    # 오른쪽 식을 계산한 값을 notes에 대입합니다.
    notes = phase4_app.data_root / "docs" / "notes"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    notes.mkdir(parents=True, exist_ok=True)
    # phase4_app.say()을 호출해 작업을 수행합니다.
    phase4_app.say("/create_file notes chain.md test")
    # 언패킹: 오른쪽 결과를 순서대로 (ok, error)에 나누어 담습니다.
    ok, error = verify_audit_chain(phase4_app.data_root / "logs")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ok, error


# pytest가 test_tampered_line_detected()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_tampered_line_detected(phase4_app: Phase4App) -> None:
    # phase4_app.chat.handle_turn()을 호출해 작업을 수행합니다.
    phase4_app.chat.handle_turn("/open_app chrome")
    # 오른쪽 식을 계산한 값을 logs에 대입합니다.
    logs = phase4_app.data_root / "logs"
    # sorted()의 반환값을 files에 대입합니다.
    files = sorted(logs.glob("audit-*.jsonl"))
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert files
    # 아래 함수()의 반환값을 lines에 대입합니다.
    lines = files[0].read_text(encoding="utf-8").splitlines()
    # json.loads()의 반환값을 record에 대입합니다.
    record = json.loads(lines[0])
    # record['args_display']에 문자열을 대입합니다.
    record["args_display"] = "tampered"
    # json.dumps()의 반환값을 lines[0]에 대입합니다.
    lines[0] = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    files[0].write_text("\n".join(lines) + "\n", encoding="utf-8")
    # 언패킹: 오른쪽 결과를 순서대로 (ok, error)에 나누어 담습니다.
    ok, error = verify_audit_chain(logs)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not ok
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert error is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "entry_hash mismatch" in error


# pytest가 test_non_monotonic_seq_detected()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_non_monotonic_seq_detected(phase4_app: Phase4App) -> None:
    # 오른쪽 식을 계산한 값을 notes에 대입합니다.
    notes = phase4_app.data_root / "docs" / "notes"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    notes.mkdir(parents=True, exist_ok=True)
    # phase4_app.say()을 호출해 작업을 수행합니다.
    phase4_app.say("/create_file notes a.md test")
    # phase4_app.say()을 호출해 작업을 수행합니다.
    phase4_app.say("/create_file notes b.md test")
    # 오른쪽 식을 계산한 값을 logs에 대입합니다.
    logs = phase4_app.data_root / "logs"
    # sorted()의 반환값을 files에 대입합니다.
    files = sorted(logs.glob("audit-*.jsonl"))
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert files
    # 아래 함수()의 반환값을 lines에 대입합니다.
    lines = files[0].read_text(encoding="utf-8").splitlines()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(lines) >= 2
    # json.loads()의 반환값을 record2에 대입합니다.
    record2 = json.loads(lines[1])
    # record2['seq']에 숫자 등 고정된 값을 대입합니다.
    record2["seq"] = 1  # non-monotonic duplicate seq
    # json.dumps()의 반환값을 lines[1]에 대입합니다.
    lines[1] = json.dumps(record2, ensure_ascii=False, separators=(",", ":"))
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    files[0].write_text("\n".join(lines) + "\n", encoding="utf-8")
    # 언패킹: 오른쪽 결과를 순서대로 (ok, error)에 나누어 담습니다.
    ok, error = verify_audit_chain(logs)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not ok
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert error is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "seq not monotonic" in error

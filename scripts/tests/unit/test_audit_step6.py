# 파이썬 공부 | scripts/tests/unit/test_audit_step6.py
# audit_step6 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Unit tests for Phase 4 Step 6: Audit log Intent flushing and Hash Chain integrity."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.clock import SystemClock
from app.core.context import RequestContext
from app.memory.migrations import initialize_database
from app.telemetry.audit import JsonlAuditWriter, read_audit_records, verify_audit_chain

# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9))
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 9, 1, 15, 0, 0, tzinfo=KST)


# audit_environment(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def audit_environment(tmp_path: Path):
    # 오른쪽 식을 계산한 값을 logs_dir에 대입합니다.
    logs_dir = tmp_path / "logs"
    # 오른쪽 식을 계산한 값을 db_path에 대입합니다.
    db_path = tmp_path / "memory" / "jarvis.sqlite3"
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(db_path, created_at=NOW)

    # JsonlAuditWriter()의 반환값을 writer에 대입합니다.
    writer = JsonlAuditWriter(
        logs_dir=logs_dir,
        database_path=db_path,
        clock=SystemClock(),
        fsync=False,
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return writer, logs_dir


# pytest가 test_step6_intent_and_result_hash_chain()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: audit_environment.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_step6_intent_and_result_hash_chain(audit_environment) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (writer, logs_dir)에 나누어 담습니다.
    writer, logs_dir = audit_environment

    # 1. Write 'intent' record (Step 6)
    # 열린 출력 대상에 데이터를 기록합니다.
    writer.write({
        "phase": "intent",
        "request_id": "req_1",
        "session_id": "ses_1",
        "tool_name": "create_file",
        "risk": "medium",
        "decision": "confirm",
        "args_hash": "hash_abc123",
        "args_display": "새 파일 생성: memo.txt",
        "normalized_args": {"root": "notes", "path": "memo.txt"},
        "approval": {"ticket_id": "apv_1", "method": "user_text"},
        "result": None,
    })

    # 2. Write 'result' record (Step 8)
    # 열린 출력 대상에 데이터를 기록합니다.
    writer.write({
        "phase": "result",
        "request_id": "req_1",
        "session_id": "ses_1",
        "tool_name": "create_file",
        "risk": "medium",
        "decision": "confirm",
        "args_hash": "hash_abc123",
        "args_display": "새 파일 생성: memo.txt",
        "normalized_args": {"root": "notes", "path": "memo.txt"},
        "approval": {"ticket_id": "apv_1", "method": "user_text"},
        "result": {"ok": True, "duration_ms": 10, "changed_paths": ["memo.txt"]},
    })

    # read_audit_records()의 반환값을 records에 대입합니다.
    records = read_audit_records(logs_dir)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(records) == 2
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert records[0]["phase"] == "intent"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert records[1]["phase"] == "result"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert records[0]["seq"] == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert records[1]["seq"] == 2
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert records[1]["prev_hash"] == records[0]["entry_hash"]

    # Verify blockchain-style hash chain integrity
    # 언패킹: 오른쪽 결과를 순서대로 (ok, error)에 나누어 담습니다.
    ok, error = verify_audit_chain(logs_dir)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ok is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert error is None


# pytest가 test_step6_audit_tampering_detected()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: audit_environment.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_step6_audit_tampering_detected(audit_environment) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (writer, logs_dir)에 나누어 담습니다.
    writer, logs_dir = audit_environment

    # 열린 출력 대상에 데이터를 기록합니다.
    writer.write({"phase": "intent", "tool_name": "open_app", "result": None})
    # 열린 출력 대상에 데이터를 기록합니다.
    writer.write({"phase": "result", "tool_name": "open_app", "result": {"ok": True}})

    # next()의 반환값을 audit_file에 대입합니다.
    audit_file = next(logs_dir.glob("audit-*.jsonl"))
    # 아래 함수()의 반환값을 lines에 대입합니다.
    lines = audit_file.read_text(encoding="utf-8").splitlines()

    # Tamper with the first record content
    # json.loads()의 반환값을 first_record에 대입합니다.
    first_record = json.loads(lines[0])
    # first_record['tool_name']에 문자열을 대입합니다.
    first_record["tool_name"] = "tampered_tool"  # malicious edit
    # tampered_lines에 리스트(순서가 있고 수정 가능)을 대입합니다.
    tampered_lines = [json.dumps(first_record, ensure_ascii=False), lines[1]]
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    audit_file.write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")

    # Hash chain verification must catch the tampering
    # 언패킹: 오른쪽 결과를 순서대로 (ok, error)에 나누어 담습니다.
    ok, error = verify_audit_chain(logs_dir)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ok is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "entry_hash mismatch" in str(error) or "prev_hash mismatch" in str(error)

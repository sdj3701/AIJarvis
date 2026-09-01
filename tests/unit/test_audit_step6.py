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

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 1, 15, 0, 0, tzinfo=KST)


@pytest.fixture
def audit_environment(tmp_path: Path):
    logs_dir = tmp_path / "logs"
    db_path = tmp_path / "memory" / "jarvis.sqlite3"
    initialize_database(db_path, created_at=NOW)

    writer = JsonlAuditWriter(
        logs_dir=logs_dir,
        database_path=db_path,
        clock=SystemClock(),
        fsync=False,
    )
    return writer, logs_dir


def test_step6_intent_and_result_hash_chain(audit_environment) -> None:
    writer, logs_dir = audit_environment

    # 1. Write 'intent' record (Step 6)
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

    records = read_audit_records(logs_dir)
    assert len(records) == 2
    assert records[0]["phase"] == "intent"
    assert records[1]["phase"] == "result"
    assert records[0]["seq"] == 1
    assert records[1]["seq"] == 2
    assert records[1]["prev_hash"] == records[0]["entry_hash"]

    # Verify blockchain-style hash chain integrity
    ok, error = verify_audit_chain(logs_dir)
    assert ok is True
    assert error is None


def test_step6_audit_tampering_detected(audit_environment) -> None:
    writer, logs_dir = audit_environment

    writer.write({"phase": "intent", "tool_name": "open_app", "result": None})
    writer.write({"phase": "result", "tool_name": "open_app", "result": {"ok": True}})

    audit_file = next(logs_dir.glob("audit-*.jsonl"))
    lines = audit_file.read_text(encoding="utf-8").splitlines()

    # Tamper with the first record content
    first_record = json.loads(lines[0])
    first_record["tool_name"] = "tampered_tool"  # malicious edit
    tampered_lines = [json.dumps(first_record, ensure_ascii=False), lines[1]]
    audit_file.write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")

    # Hash chain verification must catch the tampering
    ok, error = verify_audit_chain(logs_dir)
    assert ok is False
    assert "entry_hash mismatch" in str(error) or "prev_hash mismatch" in str(error)

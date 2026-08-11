"""Audit log hash chain and denied-call coverage."""

from __future__ import annotations

import json

import pytest

from app.telemetry.audit import verify_audit_chain
from tests.helpers.phase4_app import Phase4App

pytestmark = [pytest.mark.phase4, pytest.mark.security]


def test_denied_call_is_audited(phase4_app: Phase4App) -> None:
    outcome = phase4_app.chat.handle_turn("/open_app evilapp")
    assert not outcome.ok
    records = phase4_app.audit()
    assert records
    denied = [record for record in records if record.get("phase") == "denied"]
    assert denied
    assert denied[-1]["cause"] in {"arg_invalid", "policy_denied", "tool_not_found"}


def test_audit_chain_links(phase4_app: Phase4App) -> None:
    notes = phase4_app.data_root / "docs" / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    phase4_app.say("/create_file notes chain.md test")
    ok, error = verify_audit_chain(phase4_app.data_root / "logs")
    assert ok, error


def test_tampered_line_detected(phase4_app: Phase4App) -> None:
    phase4_app.chat.handle_turn("/open_app chrome")
    logs = phase4_app.data_root / "logs"
    files = sorted(logs.glob("audit-*.jsonl"))
    assert files
    lines = files[0].read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["args_display"] = "tampered"
    lines[0] = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    files[0].write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, error = verify_audit_chain(logs)
    assert not ok
    assert error is not None

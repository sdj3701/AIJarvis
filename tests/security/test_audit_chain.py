"""Audit log hash chain and denied-call coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.errors import ApprovalMismatch
from app.llm.base import ToolCall
from app.telemetry.audit import verify_audit_chain, verify_audit_chain_report
from scripts.gate import main as gate_main
from tests.helpers.phase4_app import NOW, Phase4App
from tests.security.test_approval_binding import _ctx

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


@pytest.mark.phase6
def test_broken_trailing_line_detected(phase4_app: Phase4App) -> None:
    phase4_app.chat.handle_turn("/open_app chrome")
    logs = phase4_app.data_root / "logs"
    files = sorted(logs.glob("audit-*.jsonl"))
    assert files
    with files[0].open("a", encoding="utf-8") as stream:
        stream.write('{"seq":999,"broken"')
    report = verify_audit_chain_report(logs)
    assert not report.ok
    assert report.issue_kind == "broken_json"
    assert report.error is not None


@pytest.mark.phase6
def test_gate_verify_audit_cli(phase4_app: Phase4App, config_dir: Path) -> None:
    phase4_app.chat.handle_turn("/open_app chrome")
    assert gate_main(["--verify-audit", "--config-dir", str(config_dir)]) == 0


def test_tool_name_change_invalidates_ticket(phase4_app: Phase4App) -> None:
    call = ToolCall(
        id="name-change",
        name="create_file",
        arguments={"root": "notes", "relative_path": "n.md", "content": "x"},
    )
    context = _ctx(phase4_app)
    outcome = phase4_app.chat.execute_tool_call(call, ctx=context)
    verdict = outcome.pending_approval
    assert verdict is not None
    ticket = phase4_app.runtime.approval_store.grant(
        verdict,
        ctx=context,
        method="user_text",
    )
    with pytest.raises(ApprovalMismatch):
        phase4_app.runtime.approval_store.consume(
            ticket.id,
            tool_name="open_folder",
            args_hash=verdict.args_hash,
            now=NOW,
        )

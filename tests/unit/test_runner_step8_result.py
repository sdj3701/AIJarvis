"""Unit tests for Phase 4 Step 8: Audit Result recording, exit codes, and ToolResult return."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.config.models import ApprovalPolicy, NetworkPolicy, SandboxPolicy, ToolDefinition, ToolLimits, ToolPolicy
from app.core.context import RequestContext
from app.core.errors import ToolNotFound
from app.core.ids import SystemIdFactory
from app.llm.base import ToolCall
from app.privacy.gate import PrivacyGate
from app.safety.approval import InMemoryApprovalStore
from app.safety.gate import SafetyGate
from app.safety.paths import Sandbox
from app.tools.base import ToolContext, ToolResult, ToolSpec
from app.tools.registry import ToolRegistry
from app.tools.runner import ToolRunner

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=KST)


class DummyAuditWriter:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def write(self, record: dict) -> None:
        self.records.append(record)


class MockSuccessTool:
    spec = ToolSpec(
        name="success_tool",
        description="성공 도구",
        json_schema={"type": "object"},
        risk="low",
        capabilities=frozenset(["fs_write"]),
        execution_mode="in_process",
        idempotent=True,
        enabled=True,
        untrusted_output=False,
        timeout_s=10,
        phase=4,
    )

    def run(self, args: dict, tctx: ToolContext) -> ToolResult:
        return ToolResult(
            ok=True,
            output="성공 완료",
            data={"status": "done"},
            error=None,
            changed_paths=("output.txt",),
            duration_ms=12,
            truncated=False,
            untrusted=False,
        )


class MockFailingTool:
    spec = ToolSpec(
        name="failing_tool",
        description="실패 도구",
        json_schema={"type": "object"},
        risk="low",
        capabilities=frozenset(["fs_read"]),
        execution_mode="in_process",
        idempotent=True,
        enabled=True,
        untrusted_output=False,
        timeout_s=10,
        phase=4,
    )

    def run(self, args: dict, tctx: ToolContext) -> ToolResult:
        raise RuntimeError("디스크 I/O 치명적 오류 발생")


@pytest.fixture
def step8_environment(tmp_path: Path):
    policy = ToolPolicy(
        schema_version=1,
        default="deny",
        approval=ApprovalPolicy(ticket_ttl_s=120, typed_confirm_phrase="실행합니다", voice_max_risk="medium"),
        limits=ToolLimits(
            max_arg_len=512,
            max_args_bytes=8192,
            max_output_bytes=65536,
            max_concurrent_tools=2,
            default_timeout_s=20,
            deny_child_processes=True,
            env_allowlist=["SystemRoot"],
        ),
        sandbox=SandboxPolicy(
            write_roots=["docs"],
            read_roots=["docs"],
            roots={"docs": "docs"},
            deny_paths=[],
            follow_reparse_points=False,
            deny_unc_paths=True,
            deny_device_paths=True,
            forbidden_write_extensions=[".exe"],
            allowed_write_extensions=[".md", ".txt"],
        ),
        network=NetworkPolicy(
            allowed_schemes=["http", "https"],
            deny_loopback=True,
            deny_private_ranges=True,
            deny_credentials_in_url=True,
            deny_mixed_script_idn=True,
            url_allowlist=[],
        ),
        tools=[
            ToolDefinition(
                name="success_tool",
                enabled=True,
                phase=4,
                risk="low",
                capabilities=["fs_write"],
                execution_mode="in_process",
                idempotent=True,
                untrusted_output=False,
                timeout_s=10,
                description="성공 도구",
            ),
            ToolDefinition(
                name="failing_tool",
                enabled=True,
                phase=4,
                risk="low",
                capabilities=["fs_read"],
                execution_mode="in_process",
                idempotent=True,
                untrusted_output=False,
                timeout_s=10,
                description="실패 도구",
            ),
        ],
        forbidden=[],
    )
    sandbox = Sandbox(data_root=tmp_path)
    gate = SafetyGate(policy=policy, sandbox=sandbox, network=policy.network, definitions={item.name: item for item in policy.tools})
    approvals = InMemoryApprovalStore(ids=SystemIdFactory(), ticket_ttl_s=120, voice_max_risk="medium")
    audit = DummyAuditWriter()
    registry = ToolRegistry(
        tools={"success_tool": MockSuccessTool(), "failing_tool": MockFailingTool()},
        specs={"success_tool": MockSuccessTool.spec, "failing_tool": MockFailingTool.spec},
    )

    runner = ToolRunner(
        registry=registry,
        gate=gate,
        approvals=approvals,
        audit_writer=audit,  # type: ignore[arg-type]
        sandbox=sandbox,
        max_concurrent=2,
        max_output_bytes=65536,
        env_allowlist=("SystemRoot",),
        default_timeout_s=20,
        privacy=PrivacyGate(),
    )
    return runner, audit


def test_step8_success_audit_result_and_tool_result_return(step8_environment) -> None:
    runner, audit = step8_environment
    ctx = MagicMock(spec=RequestContext)
    ctx.request_id = "req_step8_1"
    ctx.session_id = "ses_step8_1"
    ctx.task_id = "task_step8_1"
    ctx.channel = "text"
    ctx.interactive = True
    ctx.clock.now.return_value = NOW

    call = ToolCall(id="call_s1", name="success_tool", arguments={})
    result = runner.execute(call, ctx=ctx)

    # 1. Check ToolResult return value
    assert result.ok is True
    assert result.output == "성공 완료"
    assert result.changed_paths == ("output.txt",)
    assert result.duration_ms == 12

    # 2. Check Audit records (Intent and Result pair)
    assert len(audit.records) == 2
    intent_record = audit.records[0]
    result_record = audit.records[1]

    assert intent_record["phase"] == "intent"
    assert intent_record["tool_name"] == "success_tool"
    assert intent_record["result"] is None

    assert result_record["phase"] == "result"
    assert result_record["tool_name"] == "success_tool"
    assert result_record["result"]["ok"] is True
    assert result_record["result"]["exit_code"] == 0
    assert result_record["result"]["changed_paths"] == ["output.txt"]
    assert result_record["result"]["error"] is None


def test_step8_failure_exception_audit_result_logged(step8_environment) -> None:
    runner, audit = step8_environment
    ctx = MagicMock(spec=RequestContext)
    ctx.request_id = "req_step8_2"
    ctx.session_id = "ses_step8_2"
    ctx.task_id = None
    ctx.channel = "text"
    ctx.interactive = True
    ctx.clock.now.return_value = NOW

    call = ToolCall(id="call_f1", name="failing_tool", arguments={})
    result = runner.execute(call, ctx=ctx)

    # 1. Returns ToolResult with ok=False and caught error
    assert result.ok is False
    assert "치명적 오류" in result.output
    assert result.error == "디스크 I/O 치명적 오류 발생"

    # 2. Audit result record reflects exit_code: 1 and error details
    assert len(audit.records) == 2
    result_record = audit.records[1]
    assert result_record["phase"] == "result"
    assert result_record["result"]["ok"] is False
    assert result_record["result"]["exit_code"] == 1
    assert "치명적 오류" in result_record["result"]["error"]


def test_step8_denied_audit_logged_for_unregistered_tool(step8_environment) -> None:
    runner, audit = step8_environment
    ctx = MagicMock(spec=RequestContext)
    ctx.request_id = "req_step8_3"
    ctx.session_id = "ses_step8_3"
    ctx.task_id = None
    ctx.channel = "text"
    ctx.interactive = True
    ctx.clock.now.return_value = NOW

    call = ToolCall(id="call_u1", name="unregistered_tool", arguments={})
    with pytest.raises(ToolNotFound):
        runner.execute(call, ctx=ctx)

    # Audit denied record must be written
    assert len(audit.records) == 1
    denied_record = audit.records[0]
    assert denied_record["phase"] == "denied"
    assert denied_record["cause"] == "tool_not_found"

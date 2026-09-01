"""Unit tests for Phase 4 Step 5: Hash binding re-evaluation and ticket consumption."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.config.models import ApprovalPolicy, NetworkPolicy, SandboxPolicy, ToolDefinition, ToolLimits, ToolPolicy
from app.core.context import RequestContext
from app.core.errors import ApprovalMismatch, ApprovalRequired
from app.core.ids import SystemIdFactory
from app.llm.base import ToolCall
from app.privacy.gate import PrivacyGate
from app.safety.approval import ApprovalTicket, InMemoryApprovalStore
from app.safety.gate import SafetyGate, Verdict
from app.safety.paths import Sandbox
from app.telemetry.audit import JsonlAuditWriter
from app.tools.base import ToolContext, ToolResult, ToolSpec
from app.tools.registry import ToolRegistry
from app.tools.runner import ToolRunner

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 1, 14, 0, 0, tzinfo=KST)


class DummyAuditWriter:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def write(self, record: dict) -> None:
        self.records.append(record)


class FakeFileTool:
    spec = ToolSpec(
        name="create_file",
        description="파일 생성",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["root", "relative_path", "content"],
            "properties": {
                "root": {"type": "string", "enum": ["notes"]},
                "relative_path": {"type": "string"},
                "content": {"type": "string"},
                "overwrite": {"type": "boolean"},
            },
        },
        risk="medium",
        capabilities=frozenset(["fs_write"]),
        execution_mode="in_process",
        idempotent=False,
        enabled=True,
        untrusted_output=False,
        timeout_s=10,
        phase=4,
    )

    def run(self, args: dict, tctx: ToolContext) -> ToolResult:
        return ToolResult(
            ok=True,
            output="파일이 생성되었습니다.",
            data=args,
            error=None,
            changed_paths=(args.get("relative_path", ""),),
            duration_ms=5,
            truncated=False,
            untrusted=False,
        )


@pytest.fixture
def step5_runner(tmp_path: Path):
    policy = ToolPolicy(
        schema_version=1,
        default="deny",
        approval=ApprovalPolicy(
            ticket_ttl_s=120,
            typed_confirm_phrase="실행합니다",
            voice_max_risk="medium",
        ),
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
            roots={"notes": "docs\\notes"},
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
                name="create_file",
                enabled=True,
                phase=4,
                risk="medium",
                capabilities=["fs_write"],
                execution_mode="in_process",
                idempotent=False,
                untrusted_output=False,
                timeout_s=10,
                description="파일 생성",
                allowed_roots=["notes"],
            )
        ],
        forbidden=[],
    )
    sandbox = Sandbox(data_root=tmp_path)
    (tmp_path / "docs" / "notes").mkdir(parents=True, exist_ok=True)

    gate = SafetyGate(
        policy=policy,
        sandbox=sandbox,
        network=policy.network,
        definitions={item.name: item for item in policy.tools},
    )
    approvals = InMemoryApprovalStore(
        ids=SystemIdFactory(),
        ticket_ttl_s=120,
        voice_max_risk="medium",
    )
    audit = DummyAuditWriter()
    fake_tool = FakeFileTool()
    registry = ToolRegistry(
        tools={"create_file": fake_tool},
        specs={"create_file": fake_tool.spec},
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
    return runner, approvals, audit, gate


def test_step5_tampered_args_rejected(step5_runner) -> None:
    runner, approvals, audit, gate = step5_runner

    ctx = MagicMock(spec=RequestContext)
    ctx.request_id = "req_step5_1"
    ctx.session_id = "ses_step5_1"
    ctx.task_id = None
    ctx.channel = "text"
    ctx.interactive = True
    ctx.clock.now.return_value = NOW

    # 1. First call without ticket -> raises ApprovalRequired
    original_call = ToolCall(
        id="call_1",
        name="create_file",
        arguments={"root": "notes", "relative_path": "clean.txt", "content": "hello"},
    )
    with pytest.raises(ApprovalRequired) as exc_info:
        runner.execute(original_call, ctx=ctx)

    verdict = exc_info.value.verdict
    assert isinstance(verdict, Verdict)

    # 2. Grant ticket for the original call
    ticket = approvals.grant(verdict, ctx=ctx, method="user_text")

    # 3. Attacker tampers with arguments (changing relative_path to evil.txt)
    tampered_call = ToolCall(
        id="call_1",
        name="create_file",
        arguments={"root": "notes", "relative_path": "evil.txt", "content": "hello"},
    )

    # 4. Step 5 hash comparison catches mismatch and raises ApprovalMismatch
    with pytest.raises(ApprovalMismatch, match="인자 해시가 일치하지 않습니다"):
        runner.execute(tampered_call, ctx=ctx, ticket=ticket)

    # 5. Check audit log has denied entry with cause="approval_mismatch"
    denied_records = [r for r in audit.records if r.get("phase") == "denied"]
    assert len(denied_records) >= 1
    assert denied_records[-1]["cause"] == "approval_mismatch"


def test_step5_valid_ticket_consumed_and_executes(step5_runner) -> None:
    runner, approvals, audit, gate = step5_runner

    ctx = MagicMock(spec=RequestContext)
    ctx.request_id = "req_step5_2"
    ctx.session_id = "ses_step5_2"
    ctx.task_id = None
    ctx.channel = "text"
    ctx.interactive = True
    ctx.clock.now.return_value = NOW

    valid_call = ToolCall(
        id="call_2",
        name="create_file",
        arguments={"root": "notes", "relative_path": "report.txt", "content": "ok"},
    )

    # Evaluate & Grant
    verdict = gate.evaluate(valid_call, ctx=ctx, spec=FakeFileTool.spec)
    ticket = approvals.grant(verdict, ctx=ctx, method="user_text")

    # Execute with valid ticket -> succeeds
    result = runner.execute(valid_call, ctx=ctx, ticket=ticket)
    assert result.ok is True
    assert "파일이 생성되었습니다" in result.output

    # Attempting to reuse the same ticket immediately fails
    with pytest.raises(ApprovalMismatch, match="이미 사용된 승인 ticket"):
        runner.execute(valid_call, ctx=ctx, ticket=ticket)

"""Unit tests for Phase 4 Step 7: Secure Tool Runner execution modes and isolation."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config.models import ApprovalPolicy, NetworkPolicy, SandboxPolicy, ToolDefinition, ToolLimits, ToolPolicy
from app.core.context import RequestContext
from app.core.errors import ToolTimeout
from app.core.ids import SystemIdFactory
from app.llm.base import ToolCall
from app.privacy.gate import PrivacyGate
from app.safety.approval import InMemoryApprovalStore
from app.safety.gate import SafetyGate
from app.safety.paths import Sandbox
from app.tools.base import ToolContext, ToolResult, ToolSpec
from app.tools.registry import ToolRegistry
from app.tools.runner import ToolRunner, _minimal_env

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 1, 16, 0, 0, tzinfo=KST)


class DummyAudit:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def write(self, record: dict) -> None:
        self.records.append(record)


def test_minimal_env_isolation() -> None:
    allowlist = ("SystemRoot", "CUSTOM_VAR")
    with patch.dict(os.environ, {"SystemRoot": r"C:\Windows", "CUSTOM_VAR": "secret123", "EVIL_VAR": "hack"}):
        env = _minimal_env(allowlist)
        assert env["SystemRoot"] == r"C:\Windows"
        assert env["CUSTOM_VAR"] == "secret123"
        assert "EVIL_VAR" not in env
        assert env["PATH"] == ""


class ManagedTool:
    spec = ToolSpec(
        name="managed_tool",
        description="관리 프로세스 도구",
        json_schema={"type": "object"},
        risk="low",
        capabilities=frozenset(["proc_spawn"]),
        execution_mode="managed_process",
        idempotent=False,
        enabled=True,
        untrusted_output=False,
        timeout_s=5,
        phase=4,
    )

    def managed_command(self, args: dict, tctx: ToolContext) -> list[str]:
        return ["echo", "hello"]

    def run(self, args: dict, tctx: ToolContext) -> ToolResult:
        return ToolResult(
            ok=True,
            output="in_process fallback",
            data=None,
            error=None,
            changed_paths=(),
            duration_ms=0,
            truncated=False,
            untrusted=False,
        )


@pytest.fixture
def runner_fixture(tmp_path: Path):
    policy = ToolPolicy(
        schema_version=1,
        default="deny",
        approval=ApprovalPolicy(ticket_ttl_s=120, typed_confirm_phrase="실행합니다", voice_max_risk="medium"),
        limits=ToolLimits(
            max_arg_len=512,
            max_args_bytes=8192,
            max_output_bytes=100,  # small max output for truncation test
            max_concurrent_tools=2,
            default_timeout_s=10,
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
                name="managed_tool",
                enabled=True,
                phase=4,
                risk="low",
                capabilities=["proc_spawn"],
                execution_mode="managed_process",
                idempotent=False,
                untrusted_output=False,
                timeout_s=5,
                description="테스트",
            )
        ],
        forbidden=[],
    )
    sandbox = Sandbox(data_root=tmp_path)
    gate = SafetyGate(policy=policy, sandbox=sandbox, network=policy.network, definitions={item.name: item for item in policy.tools})
    approvals = InMemoryApprovalStore(ids=SystemIdFactory(), ticket_ttl_s=120, voice_max_risk="medium")
    audit = DummyAudit()
    managed_tool = ManagedTool()
    registry = ToolRegistry(tools={"managed_tool": managed_tool}, specs={"managed_tool": managed_tool.spec})

    runner = ToolRunner(
        registry=registry,
        gate=gate,
        approvals=approvals,
        audit_writer=audit,  # type: ignore[arg-type]
        sandbox=sandbox,
        max_concurrent=2,
        max_output_bytes=50,  # 50 bytes limit
        env_allowlist=("SystemRoot",),
        default_timeout_s=10,
        privacy=PrivacyGate(),
    )
    return runner, audit


def test_managed_process_execution_success(runner_fixture) -> None:
    runner, audit = runner_fixture
    ctx = MagicMock(spec=RequestContext)
    ctx.request_id = "req_managed_1"
    ctx.session_id = "ses_managed_1"
    ctx.task_id = None
    ctx.channel = "text"
    ctx.interactive = True
    ctx.clock.now.return_value = NOW

    with patch("app.tools.runner.subprocess.Popen") as mock_popen, \
         patch("app.tools.runner._assign_job_object", return_value=123), \
         patch("app.tools.runner._close_job"):
        mock_proc = MagicMock()
        mock_proc.pid = 7777
        mock_proc.communicate.return_value = (b"output result", b"")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        call = ToolCall(id="call_m1", name="managed_tool", arguments={})
        result = runner.execute(call, ctx=ctx)

        assert result.ok is True
        assert result.output == "output result"
        assert result.truncated is False
        mock_popen.assert_called_once()
        assert mock_popen.call_args.kwargs.get("shell") is False


def test_managed_process_timeout_kills_tree(runner_fixture) -> None:
    runner, audit = runner_fixture
    ctx = MagicMock(spec=RequestContext)
    ctx.request_id = "req_managed_2"
    ctx.session_id = "ses_managed_2"
    ctx.task_id = None
    ctx.channel = "text"
    ctx.interactive = True
    ctx.clock.now.return_value = NOW

    with patch("app.tools.runner.subprocess.Popen") as mock_popen, \
         patch("app.tools.runner._assign_job_object", return_value=456), \
         patch("app.tools.runner._kill_process_tree") as mock_kill, \
         patch("app.tools.runner._close_job"):
        mock_proc = MagicMock()
        mock_proc.pid = 8888
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd=["echo"], timeout=5)
        mock_popen.return_value = mock_proc

        call = ToolCall(id="call_m2", name="managed_tool", arguments={})
        result = runner.execute(call, ctx=ctx)

        assert result.ok is False
        assert "시간이 초과" in result.output
        mock_kill.assert_called_once_with(8888, 456)


def test_managed_process_output_truncation(runner_fixture) -> None:
    runner, audit = runner_fixture
    ctx = MagicMock(spec=RequestContext)
    ctx.request_id = "req_managed_3"
    ctx.session_id = "ses_managed_3"
    ctx.task_id = None
    ctx.channel = "text"
    ctx.interactive = True
    ctx.clock.now.return_value = NOW

    with patch("app.tools.runner.subprocess.Popen") as mock_popen, \
         patch("app.tools.runner._assign_job_object", return_value=None):
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        # Return 100 bytes (limit is 50)
        mock_proc.communicate.return_value = (b"A" * 100, b"")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        call = ToolCall(id="call_m3", name="managed_tool", arguments={})
        result = runner.execute(call, ctx=ctx)

        assert result.ok is True
        assert len(result.output) == 50
        assert result.truncated is True

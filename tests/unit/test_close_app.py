"""Unit tests for close_app tool and SafetyGate integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config.models import (
    ApprovalPolicy,
    NetworkPolicy,
    SandboxPolicy,
    Settings,
    ToolDefinition,
    ToolLimits,
    ToolPolicy,
)
from app.core.context import RequestContext
from app.core.ids import SystemIdFactory
from app.llm.base import ToolCall
from app.safety.gate import SafetyGate
from app.safety.paths import Sandbox
from app.tools.base import ToolContext, ToolSpec
from app.tools.impl.close_app import CloseAppTool
from app.tools.registry import schema_for_definition, validate_tool_args

pytestmark = pytest.mark.phase4


def test_close_app_schema_generation() -> None:
    defn = ToolDefinition(
        name="close_app",
        enabled=True,
        phase=4,
        risk="medium",
        capabilities=["proc_spawn"],
        execution_mode="in_process",
        idempotent=False,
        untrusted_output=False,
        timeout_s=10,
        description="허용 목록에 등록된 앱을 종료합니다.",
        app_map={"notepad": Path(r"C:\Windows\System32\notepad.exe")},
    )
    schema = schema_for_definition(defn)
    assert schema["type"] == "object"
    assert schema["required"] == ["app"]
    assert "notepad" in schema["properties"]["app"]["enum"]

    validated = validate_tool_args(schema, {"app": "notepad"})
    assert validated == {"app": "notepad"}


def test_close_app_execution_success() -> None:
    spec = ToolSpec(
        name="close_app",
        description="앱 종료",
        json_schema={},
        risk="medium",
        capabilities=frozenset(["proc_spawn"]),
        execution_mode="in_process",
        idempotent=False,
        enabled=True,
        untrusted_output=False,
        timeout_s=10,
        phase=4,
    )
    tool = CloseAppTool(spec=spec)
    tctx = ToolContext(
        ctx=MagicMock(spec=RequestContext),
        normalized_args={"app": "notepad", "exe_name": "notepad.exe"},
    )

    with patch("app.tools.impl.close_app.subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        result = tool.run({"app": "notepad"}, tctx)
        assert result.ok is True
        assert "성공적으로 종료" in result.output
        mock_run.assert_called_once_with(
            ["taskkill", "/IM", "notepad.exe", "/T", "/F"],
            capture_output=True,
            text=True,
            shell=False,
            timeout=10,
        )


def test_close_app_execution_not_found() -> None:
    spec = ToolSpec(
        name="close_app",
        description="앱 종료",
        json_schema={},
        risk="medium",
        capabilities=frozenset(["proc_spawn"]),
        execution_mode="in_process",
        idempotent=False,
        enabled=True,
        untrusted_output=False,
        timeout_s=10,
        phase=4,
    )
    tool = CloseAppTool(spec=spec)
    tctx = ToolContext(
        ctx=MagicMock(spec=RequestContext),
        normalized_args={"app": "notepad", "exe_name": "notepad.exe"},
    )

    with patch("app.tools.impl.close_app.subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 128
        mock_proc.stderr = "ERROR: The process 'notepad.exe' not found."
        mock_run.return_value = mock_proc

        result = tool.run({"app": "notepad"}, tctx)
        assert result.ok is False
        assert "실행 중이지 않거나" in result.output


def test_close_app_safety_gate_evaluation(tmp_path: Path) -> None:
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
                name="close_app",
                enabled=True,
                phase=4,
                risk="medium",
                capabilities=["proc_spawn"],
                execution_mode="in_process",
                idempotent=False,
                untrusted_output=False,
                timeout_s=10,
                description="앱 종료",
                app_map={"notepad": Path(r"C:\Windows\System32\notepad.exe")},
            )
        ],
        forbidden=[],
    )
    sandbox = Sandbox(data_root=tmp_path)
    gate = SafetyGate(
        policy=policy,
        sandbox=sandbox,
        network=policy.network,
        definitions={item.name: item for item in policy.tools},
    )

    ctx = MagicMock(spec=RequestContext)
    ctx.channel = "text"
    ctx.interactive = True

    spec = ToolSpec(
        name="close_app",
        description="앱 종료",
        json_schema={},
        risk="medium",
        capabilities=frozenset(["proc_spawn"]),
        execution_mode="in_process",
        idempotent=False,
        enabled=True,
        untrusted_output=False,
        timeout_s=10,
        phase=4,
    )

    # 1. Valid close_app call -> decision is confirm (requires approval)
    call = ToolCall(id="call_1", name="close_app", arguments={"app": "notepad"})
    verdict = gate.evaluate(call, ctx=ctx, spec=spec)
    assert verdict.decision == "confirm"
    assert verdict.risk == "medium"
    assert verdict.normalized_args["exe_name"] == "notepad.exe"
    assert "앱 종료: notepad (notepad.exe)" in verdict.display

    # 2. Unlisted app -> decision is deny
    call_invalid = ToolCall(id="call_2", name="close_app", arguments={"app": "unlisted_app"})
    verdict_invalid = gate.evaluate(call_invalid, ctx=ctx, spec=spec)
    assert verdict_invalid.decision == "deny"

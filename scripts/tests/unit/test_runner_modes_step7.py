# 파이썬 공부 | scripts/tests/unit/test_runner_modes_step7.py
# runner_modes_step7 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Unit tests for Phase 4 Step 7: Secure Tool Runner execution modes and isolation."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config.loader import load_config
from app.config.models import ApprovalPolicy, NetworkPolicy, SandboxPolicy, ToolDefinition, ToolLimits, ToolPolicy
from app.core.context import RequestContext
from app.core.errors import ToolTimeout
from app.core.ids import SystemIdFactory
from app.llm.base import ToolCall
from app.privacy.gate import PrivacyGate
from app.safety.approval import InMemoryApprovalStore
from app.safety.gate import SafetyGate
from app.safety.paths import build_sandbox
from app.tools.base import ToolContext, ToolResult, ToolSpec
from app.tools.registry import ToolRegistry
from app.tools.runner import ToolRunner, _minimal_env

# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9))
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 9, 1, 16, 0, 0, tzinfo=KST)


# DummyAudit: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class DummyAudit:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # self.records에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.records: list[dict] = []

    # write(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: record.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def write(self, record: dict) -> None:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.records.append(record)


# pytest가 test_minimal_env_isolation()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_minimal_env_isolation() -> None:
    # allowlist에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    allowlist = ("SystemRoot", "CUSTOM_VAR")
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch.dict(os.environ, {"SystemRoot": r"C:\Windows", "CUSTOM_VAR": "secret123", "EVIL_VAR": "hack"}):
        # _minimal_env()의 반환값을 env에 대입합니다.
        env = _minimal_env(allowlist)
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert env["SystemRoot"] == r"C:\Windows"
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert env["CUSTOM_VAR"] == "secret123"
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert "EVIL_VAR" not in env
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert env["PATH"] == ""


# ManagedTool: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class ManagedTool:
    # ToolSpec()의 반환값을 spec에 대입합니다.
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

    # managed_command(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: args, tctx.
    # 반환 타입 힌트: list[str].
    def managed_command(self, args: dict, tctx: ToolContext) -> list[str]:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ["echo", "hello"]

    # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: args, tctx.
    # 반환 타입 힌트: ToolResult.
    def run(self, args: dict, tctx: ToolContext) -> ToolResult:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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


# runner_fixture(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def runner_fixture(tmp_path: Path, config_dir):
    # ToolPolicy()의 반환값을 policy에 대입합니다.
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
    # Sandbox()의 반환값을 sandbox에 대입합니다.
    settings = load_config(config_dir).settings
    settings = settings.model_copy(
        update={"paths": settings.paths.model_copy(update={"data_root": tmp_path})}
    )
    sandbox = build_sandbox(settings, policy.sandbox)
    # SafetyGate()의 반환값을 gate에 대입합니다.
    gate = SafetyGate(policy=policy, sandbox=sandbox, network=policy.network, definitions={item.name: item for item in policy.tools})
    # InMemoryApprovalStore()의 반환값을 approvals에 대입합니다.
    approvals = InMemoryApprovalStore(ids=SystemIdFactory(), ticket_ttl_s=120, voice_max_risk="medium")
    # DummyAudit()의 반환값을 audit에 대입합니다.
    audit = DummyAudit()
    # ManagedTool()의 반환값을 managed_tool에 대입합니다.
    managed_tool = ManagedTool()
    # ToolRegistry()의 반환값을 registry에 대입합니다.
    registry = ToolRegistry(tools={"managed_tool": managed_tool}, specs={"managed_tool": managed_tool.spec})

    # ToolRunner()의 반환값을 runner에 대입합니다.
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
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return runner, audit


# pytest가 test_managed_process_execution_success()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: runner_fixture.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_managed_process_execution_success(runner_fixture) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (runner, audit)에 나누어 담습니다.
    runner, audit = runner_fixture
    # MagicMock()의 반환값을 ctx에 대입합니다.
    ctx = MagicMock(spec=RequestContext)
    # ctx.request_id에 문자열을 대입합니다.
    ctx.request_id = "req_managed_1"
    # ctx.session_id에 문자열을 대입합니다.
    ctx.session_id = "ses_managed_1"
    # ctx.task_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    ctx.task_id = None
    # ctx.channel에 문자열을 대입합니다.
    ctx.channel = "text"
    # ctx.interactive을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    ctx.interactive = True
    # 오른쪽 식을 계산한 값을 ctx.clock.now.return_value에 대입합니다.
    ctx.clock.now.return_value = NOW

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.runner.subprocess.Popen") as mock_popen, \
         patch("app.tools.runner._assign_job_object", return_value=123), \
         patch("app.tools.runner._close_job"):
        # MagicMock()의 반환값을 mock_proc에 대입합니다.
        mock_proc = MagicMock()
        # mock_proc.pid에 숫자 등 고정된 값을 대입합니다.
        mock_proc.pid = 7777
        # mock_proc.communicate.return_value에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
        mock_proc.communicate.return_value = (b"output result", b"")
        # mock_proc.returncode에 숫자 등 고정된 값을 대입합니다.
        mock_proc.returncode = 0
        # 오른쪽 식을 계산한 값을 mock_popen.return_value에 대입합니다.
        mock_popen.return_value = mock_proc

        # ToolCall()의 반환값을 call에 대입합니다.
        call = ToolCall(id="call_m1", name="managed_tool", arguments={})
        # runner.execute()의 반환값을 result에 대입합니다.
        result = runner.execute(call, ctx=ctx)

        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert result.ok is True
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert result.output == "output result"
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert result.truncated is False
        # mock_popen.assert_called_once()을 호출해 작업을 수행합니다.
        mock_popen.assert_called_once()
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert mock_popen.call_args.kwargs.get("shell") is False


# pytest가 test_managed_process_timeout_kills_tree()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: runner_fixture.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_managed_process_timeout_kills_tree(runner_fixture) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (runner, audit)에 나누어 담습니다.
    runner, audit = runner_fixture
    # MagicMock()의 반환값을 ctx에 대입합니다.
    ctx = MagicMock(spec=RequestContext)
    # ctx.request_id에 문자열을 대입합니다.
    ctx.request_id = "req_managed_2"
    # ctx.session_id에 문자열을 대입합니다.
    ctx.session_id = "ses_managed_2"
    # ctx.task_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    ctx.task_id = None
    # ctx.channel에 문자열을 대입합니다.
    ctx.channel = "text"
    # ctx.interactive을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    ctx.interactive = True
    # 오른쪽 식을 계산한 값을 ctx.clock.now.return_value에 대입합니다.
    ctx.clock.now.return_value = NOW

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.runner.subprocess.Popen") as mock_popen, \
         patch("app.tools.runner._assign_job_object", return_value=456), \
         patch("app.tools.runner._kill_process_tree") as mock_kill, \
         patch("app.tools.runner._close_job"):
        # MagicMock()의 반환값을 mock_proc에 대입합니다.
        mock_proc = MagicMock()
        # mock_proc.pid에 숫자 등 고정된 값을 대입합니다.
        mock_proc.pid = 8888
        # subprocess.TimeoutExpired()의 반환값을 mock_proc.communicate.side_effect에 대입합니다.
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd=["echo"], timeout=5)
        # 오른쪽 식을 계산한 값을 mock_popen.return_value에 대입합니다.
        mock_popen.return_value = mock_proc

        # ToolCall()의 반환값을 call에 대입합니다.
        call = ToolCall(id="call_m2", name="managed_tool", arguments={})
        # runner.execute()의 반환값을 result에 대입합니다.
        result = runner.execute(call, ctx=ctx)

        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert result.ok is False
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert "시간이 초과" in result.output
        # mock_kill.assert_called_once_with()을 호출해 작업을 수행합니다.
        mock_kill.assert_called_once_with(8888, 456)


# pytest가 test_managed_process_output_truncation()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: runner_fixture.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_managed_process_output_truncation(runner_fixture) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (runner, audit)에 나누어 담습니다.
    runner, audit = runner_fixture
    # MagicMock()의 반환값을 ctx에 대입합니다.
    ctx = MagicMock(spec=RequestContext)
    # ctx.request_id에 문자열을 대입합니다.
    ctx.request_id = "req_managed_3"
    # ctx.session_id에 문자열을 대입합니다.
    ctx.session_id = "ses_managed_3"
    # ctx.task_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    ctx.task_id = None
    # ctx.channel에 문자열을 대입합니다.
    ctx.channel = "text"
    # ctx.interactive을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    ctx.interactive = True
    # 오른쪽 식을 계산한 값을 ctx.clock.now.return_value에 대입합니다.
    ctx.clock.now.return_value = NOW

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.runner.subprocess.Popen") as mock_popen, \
         patch("app.tools.runner._assign_job_object", return_value=None):
        # MagicMock()의 반환값을 mock_proc에 대입합니다.
        mock_proc = MagicMock()
        # mock_proc.pid에 숫자 등 고정된 값을 대입합니다.
        mock_proc.pid = 9999
        # Return 100 bytes (limit is 50)
        # mock_proc.communicate.return_value에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
        mock_proc.communicate.return_value = (b"A" * 100, b"")
        # mock_proc.returncode에 숫자 등 고정된 값을 대입합니다.
        mock_proc.returncode = 0
        # 오른쪽 식을 계산한 값을 mock_popen.return_value에 대입합니다.
        mock_popen.return_value = mock_proc

        # ToolCall()의 반환값을 call에 대입합니다.
        call = ToolCall(id="call_m3", name="managed_tool", arguments={})
        # runner.execute()의 반환값을 result에 대입합니다.
        result = runner.execute(call, ctx=ctx)

        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert result.ok is True
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert len(result.output) == 50
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert result.truncated is True

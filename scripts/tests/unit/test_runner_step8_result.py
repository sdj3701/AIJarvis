# 파이썬 공부 | scripts/tests/unit/test_runner_step8_result.py
# runner_step8_result 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Unit tests for Phase 4 Step 8: Audit Result recording, exit codes, and ToolResult return."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.config.loader import load_config
from app.config.models import ApprovalPolicy, NetworkPolicy, SandboxPolicy, ToolDefinition, ToolLimits, ToolPolicy
from app.core.context import RequestContext
from app.core.errors import ToolNotFound
from app.core.ids import SystemIdFactory
from app.llm.base import ToolCall
from app.privacy.gate import PrivacyGate
from app.safety.approval import InMemoryApprovalStore
from app.safety.gate import SafetyGate
from app.safety.paths import build_sandbox
from app.tools.base import ToolContext, ToolResult, ToolSpec
from app.tools.registry import ToolRegistry
from app.tools.runner import ToolRunner

# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9))
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=KST)


# DummyAuditWriter: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class DummyAuditWriter:
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


# MockSuccessTool: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class MockSuccessTool:
    # ToolSpec()의 반환값을 spec에 대입합니다.
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

    # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: args, tctx.
    # 반환 타입 힌트: ToolResult.
    def run(self, args: dict, tctx: ToolContext) -> ToolResult:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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


# MockFailingTool: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class MockFailingTool:
    # ToolSpec()의 반환값을 spec에 대입합니다.
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

    # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: args, tctx.
    # 반환 타입 힌트: ToolResult.
    def run(self, args: dict, tctx: ToolContext) -> ToolResult:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise RuntimeError("디스크 I/O 치명적 오류 발생")


# step8_environment(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def step8_environment(tmp_path: Path, config_dir):
    # ToolPolicy()의 반환값을 policy에 대입합니다.
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
    # DummyAuditWriter()의 반환값을 audit에 대입합니다.
    audit = DummyAuditWriter()
    # ToolRegistry()의 반환값을 registry에 대입합니다.
    registry = ToolRegistry(
        tools={"success_tool": MockSuccessTool(), "failing_tool": MockFailingTool()},
        specs={"success_tool": MockSuccessTool.spec, "failing_tool": MockFailingTool.spec},
    )

    # ToolRunner()의 반환값을 runner에 대입합니다.
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
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return runner, audit


# pytest가 test_step8_success_audit_result_and_tool_result_return()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: step8_environment.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_step8_success_audit_result_and_tool_result_return(step8_environment) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (runner, audit)에 나누어 담습니다.
    runner, audit = step8_environment
    # MagicMock()의 반환값을 ctx에 대입합니다.
    ctx = MagicMock(spec=RequestContext)
    # ctx.request_id에 문자열을 대입합니다.
    ctx.request_id = "req_step8_1"
    # ctx.session_id에 문자열을 대입합니다.
    ctx.session_id = "ses_step8_1"
    # ctx.task_id에 문자열을 대입합니다.
    ctx.task_id = "task_step8_1"
    # ctx.channel에 문자열을 대입합니다.
    ctx.channel = "text"
    # ctx.interactive을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    ctx.interactive = True
    # 오른쪽 식을 계산한 값을 ctx.clock.now.return_value에 대입합니다.
    ctx.clock.now.return_value = NOW

    # ToolCall()의 반환값을 call에 대입합니다.
    call = ToolCall(id="call_s1", name="success_tool", arguments={})
    # runner.execute()의 반환값을 result에 대입합니다.
    result = runner.execute(call, ctx=ctx)

    # 1. Check ToolResult return value
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.ok is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.output == "성공 완료"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.changed_paths == ("output.txt",)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.duration_ms == 12

    # 2. Check Audit records (Intent and Result pair)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(audit.records) == 2
    # 오른쪽 식을 계산한 값을 intent_record에 대입합니다.
    intent_record = audit.records[0]
    # 오른쪽 식을 계산한 값을 result_record에 대입합니다.
    result_record = audit.records[1]

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert intent_record["phase"] == "intent"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert intent_record["tool_name"] == "success_tool"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert intent_record["result"] is None

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result_record["phase"] == "result"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result_record["tool_name"] == "success_tool"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result_record["result"]["ok"] is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result_record["result"]["exit_code"] == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result_record["result"]["changed_paths"] == ["output.txt"]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result_record["result"]["error"] is None


# pytest가 test_step8_failure_exception_audit_result_logged()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: step8_environment.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_step8_failure_exception_audit_result_logged(step8_environment) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (runner, audit)에 나누어 담습니다.
    runner, audit = step8_environment
    # MagicMock()의 반환값을 ctx에 대입합니다.
    ctx = MagicMock(spec=RequestContext)
    # ctx.request_id에 문자열을 대입합니다.
    ctx.request_id = "req_step8_2"
    # ctx.session_id에 문자열을 대입합니다.
    ctx.session_id = "ses_step8_2"
    # ctx.task_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    ctx.task_id = None
    # ctx.channel에 문자열을 대입합니다.
    ctx.channel = "text"
    # ctx.interactive을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    ctx.interactive = True
    # 오른쪽 식을 계산한 값을 ctx.clock.now.return_value에 대입합니다.
    ctx.clock.now.return_value = NOW

    # ToolCall()의 반환값을 call에 대입합니다.
    call = ToolCall(id="call_f1", name="failing_tool", arguments={})
    # runner.execute()의 반환값을 result에 대입합니다.
    result = runner.execute(call, ctx=ctx)

    # 1. Returns ToolResult with ok=False and caught error
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.ok is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "치명적 오류" in result.output
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.error == "디스크 I/O 치명적 오류 발생"

    # 2. Audit result record reflects exit_code: 1 and error details
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(audit.records) == 2
    # 오른쪽 식을 계산한 값을 result_record에 대입합니다.
    result_record = audit.records[1]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result_record["phase"] == "result"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result_record["result"]["ok"] is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result_record["result"]["exit_code"] == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "치명적 오류" in result_record["result"]["error"]


# pytest가 test_step8_denied_audit_logged_for_unregistered_tool()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: step8_environment.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_step8_denied_audit_logged_for_unregistered_tool(step8_environment) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (runner, audit)에 나누어 담습니다.
    runner, audit = step8_environment
    # MagicMock()의 반환값을 ctx에 대입합니다.
    ctx = MagicMock(spec=RequestContext)
    # ctx.request_id에 문자열을 대입합니다.
    ctx.request_id = "req_step8_3"
    # ctx.session_id에 문자열을 대입합니다.
    ctx.session_id = "ses_step8_3"
    # ctx.task_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    ctx.task_id = None
    # ctx.channel에 문자열을 대입합니다.
    ctx.channel = "text"
    # ctx.interactive을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    ctx.interactive = True
    # 오른쪽 식을 계산한 값을 ctx.clock.now.return_value에 대입합니다.
    ctx.clock.now.return_value = NOW

    # ToolCall()의 반환값을 call에 대입합니다.
    call = ToolCall(id="call_u1", name="unregistered_tool", arguments={})
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ToolNotFound):
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        runner.execute(call, ctx=ctx)

    # Audit denied record must be written
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(audit.records) == 1
    # 오른쪽 식을 계산한 값을 denied_record에 대입합니다.
    denied_record = audit.records[0]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert denied_record["phase"] == "denied"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert denied_record["cause"] == "tool_not_found"

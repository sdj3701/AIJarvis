# 파이썬 공부 | scripts/tests/unit/test_runner_execution_step5.py
# runner_execution_step5 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Unit tests for Phase 4 Step 5: Hash binding re-evaluation and ticket consumption."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.config.loader import load_config
from app.config.models import ApprovalPolicy, NetworkPolicy, SandboxPolicy, ToolDefinition, ToolLimits, ToolPolicy
from app.core.context import RequestContext
from app.core.errors import ApprovalMismatch, ApprovalRequired
from app.core.ids import SystemIdFactory
from app.llm.base import ToolCall
from app.privacy.gate import PrivacyGate
from app.safety.approval import ApprovalTicket, InMemoryApprovalStore
from app.safety.gate import SafetyGate, Verdict
from app.safety.paths import build_sandbox
from app.telemetry.audit import JsonlAuditWriter
from app.tools.base import ToolContext, ToolResult, ToolSpec
from app.tools.registry import ToolRegistry
from app.tools.runner import ToolRunner

# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9))
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 9, 1, 14, 0, 0, tzinfo=KST)


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


# FakeFileTool: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeFileTool:
    # ToolSpec()의 반환값을 spec에 대입합니다.
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

    # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: args, tctx.
    # 반환 타입 힌트: ToolResult.
    def run(self, args: dict, tctx: ToolContext) -> ToolResult:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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


# step5_runner(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def step5_runner(tmp_path: Path, config_dir):
    # ToolPolicy()의 반환값을 policy에 대입합니다.
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
    # Sandbox()의 반환값을 sandbox에 대입합니다.
    settings = load_config(config_dir).settings
    settings = settings.model_copy(
        update={"paths": settings.paths.model_copy(update={"data_root": tmp_path})}
    )
    sandbox = build_sandbox(settings, policy.sandbox)
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    (tmp_path / "docs" / "notes").mkdir(parents=True, exist_ok=True)

    # SafetyGate()의 반환값을 gate에 대입합니다.
    gate = SafetyGate(
        policy=policy,
        sandbox=sandbox,
        network=policy.network,
        definitions={item.name: item for item in policy.tools},
    )
    # InMemoryApprovalStore()의 반환값을 approvals에 대입합니다.
    approvals = InMemoryApprovalStore(
        ids=SystemIdFactory(),
        ticket_ttl_s=120,
        voice_max_risk="medium",
    )
    # DummyAuditWriter()의 반환값을 audit에 대입합니다.
    audit = DummyAuditWriter()
    # FakeFileTool()의 반환값을 fake_tool에 대입합니다.
    fake_tool = FakeFileTool()
    # ToolRegistry()의 반환값을 registry에 대입합니다.
    registry = ToolRegistry(
        tools={"create_file": fake_tool},
        specs={"create_file": fake_tool.spec},
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
    return runner, approvals, audit, gate


# pytest가 test_step5_tampered_args_rejected()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: step5_runner.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_step5_tampered_args_rejected(step5_runner) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (runner, approvals, audit, gate)에 나누어 담습니다.
    runner, approvals, audit, gate = step5_runner

    # MagicMock()의 반환값을 ctx에 대입합니다.
    ctx = MagicMock(spec=RequestContext)
    # ctx.request_id에 문자열을 대입합니다.
    ctx.request_id = "req_step5_1"
    # ctx.session_id에 문자열을 대입합니다.
    ctx.session_id = "ses_step5_1"
    # ctx.task_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    ctx.task_id = None
    # ctx.channel에 문자열을 대입합니다.
    ctx.channel = "text"
    # ctx.interactive을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    ctx.interactive = True
    # 오른쪽 식을 계산한 값을 ctx.clock.now.return_value에 대입합니다.
    ctx.clock.now.return_value = NOW

    # 1. First call without ticket -> raises ApprovalRequired
    # ToolCall()의 반환값을 original_call에 대입합니다.
    original_call = ToolCall(
        id="call_1",
        name="create_file",
        arguments={"root": "notes", "relative_path": "clean.txt", "content": "hello"},
    )
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ApprovalRequired) as exc_info:
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        runner.execute(original_call, ctx=ctx)

    # 오른쪽 식을 계산한 값을 verdict에 대입합니다.
    verdict = exc_info.value.verdict
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert isinstance(verdict, Verdict)

    # 2. Grant ticket for the original call
    # approvals.grant()의 반환값을 ticket에 대입합니다.
    ticket = approvals.grant(verdict, ctx=ctx, method="user_text")

    # 3. Attacker tampers with arguments (changing relative_path to evil.txt)
    # ToolCall()의 반환값을 tampered_call에 대입합니다.
    tampered_call = ToolCall(
        id="call_1",
        name="create_file",
        arguments={"root": "notes", "relative_path": "evil.txt", "content": "hello"},
    )

    # 4. Step 5 hash comparison catches mismatch and raises ApprovalMismatch
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ApprovalMismatch, match="인자 해시가 일치하지 않습니다"):
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        runner.execute(tampered_call, ctx=ctx, ticket=ticket)

    # 5. Check audit log has denied entry with cause="approval_mismatch"
    # 오른쪽 식을 계산한 값을 denied_records에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    denied_records = [r for r in audit.records if r.get("phase") == "denied"]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(denied_records) >= 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert denied_records[-1]["cause"] == "approval_mismatch"


# pytest가 test_step5_valid_ticket_consumed_and_executes()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: step5_runner.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_step5_valid_ticket_consumed_and_executes(step5_runner) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (runner, approvals, audit, gate)에 나누어 담습니다.
    runner, approvals, audit, gate = step5_runner

    # MagicMock()의 반환값을 ctx에 대입합니다.
    ctx = MagicMock(spec=RequestContext)
    # ctx.request_id에 문자열을 대입합니다.
    ctx.request_id = "req_step5_2"
    # ctx.session_id에 문자열을 대입합니다.
    ctx.session_id = "ses_step5_2"
    # ctx.task_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    ctx.task_id = None
    # ctx.channel에 문자열을 대입합니다.
    ctx.channel = "text"
    # ctx.interactive을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    ctx.interactive = True
    # 오른쪽 식을 계산한 값을 ctx.clock.now.return_value에 대입합니다.
    ctx.clock.now.return_value = NOW

    # ToolCall()의 반환값을 valid_call에 대입합니다.
    valid_call = ToolCall(
        id="call_2",
        name="create_file",
        arguments={"root": "notes", "relative_path": "report.txt", "content": "ok"},
    )

    # Evaluate & Grant
    # gate.evaluate()의 반환값을 verdict에 대입합니다.
    verdict = gate.evaluate(valid_call, ctx=ctx, spec=FakeFileTool.spec)
    # approvals.grant()의 반환값을 ticket에 대입합니다.
    ticket = approvals.grant(verdict, ctx=ctx, method="user_text")

    # Execute with valid ticket -> succeeds
    # runner.execute()의 반환값을 result에 대입합니다.
    result = runner.execute(valid_call, ctx=ctx, ticket=ticket)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.ok is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "파일이 생성되었습니다" in result.output

    # Attempting to reuse the same ticket immediately fails
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ApprovalMismatch, match="이미 사용된 승인 ticket"):
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        runner.execute(valid_call, ctx=ctx, ticket=ticket)

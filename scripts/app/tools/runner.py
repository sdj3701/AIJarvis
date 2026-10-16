# 파이썬 공부 | scripts/app/tools/runner.py
# 도구 실행 전 검사부터 실행 결과와 오류 기록까지 관리합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Secure tool execution pipeline with audit, approval, and process limits."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, cast

from app.core.context import RequestContext
from app.core.errors import (
    ApprovalMismatch,
    ApprovalRequired,
    PolicyDenied,
    ToolArgInvalid,
    ToolError,
    ToolNotFound,
    ToolTimeout,
)
from app.llm.base import ToolCall
from app.privacy.gate import PrivacyGate
from app.safety.approval import ApprovalStore, ApprovalTicket
from app.safety.gate import SafetyGate, Verdict
from app.safety.paths import Sandbox
from app.telemetry.audit import JsonlAuditWriter
from app.tools.base import ToolContext, ToolResult
from app.tools.registry import ToolRegistry, validate_tool_args

# 오른쪽 식을 계산한 값을 AuditCause에 대입합니다.
AuditCause = str


# ToolRunner: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class ToolRunner:
    # registry: ToolRegistry 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    registry: ToolRegistry
    # gate: SafetyGate 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    gate: SafetyGate
    # approvals: ApprovalStore 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    approvals: ApprovalStore
    # audit_writer: JsonlAuditWriter 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    audit_writer: JsonlAuditWriter
    # sandbox: Sandbox 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    sandbox: Sandbox
    # max_concurrent: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    max_concurrent: int
    # max_output_bytes: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    max_output_bytes: int
    # env_allowlist: tuple[str, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    env_allowlist: tuple[str, ...]
    # default_timeout_s: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    default_timeout_s: float
    # privacy: PrivacyGate 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    privacy: PrivacyGate
    # field()의 반환값을 _semaphore에 대입합니다.
    _semaphore: threading.Semaphore = field(init=False, repr=False)

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # threading.Semaphore()의 반환값을 self._semaphore에 대입합니다.
        self._semaphore = threading.Semaphore(self.max_concurrent)

    # execute(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: call, ctx, ticket.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: ToolResult.
    def execute(
        self,
        call: ToolCall,
        *,
        ctx: RequestContext,
        ticket: ApprovalTicket | None = None,
    ) -> ToolResult:
        # self.registry.specs.get()의 반환값을 spec에 대입합니다.
        spec = self.registry.specs.get(call.name)
        # self.registry.tools.get()의 반환값을 tool에 대입합니다.
        tool = self.registry.tools.get(call.name)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: spec is None or tool is None or (not
        # spec.enabled).
        if spec is None or tool is None or not spec.enabled:
            # self._audit_denied()을 호출해 작업을 수행합니다.
            self._audit_denied(
                ctx,
                call_name=call.name,
                cause="tool_not_found",
                display=f"거부: 등록되지 않은 도구 ({call.name})",
                tool_name=call.name,
                risk=None,
                capabilities=None,
                args_hash=None,
                normalized_args=None,
                decision="deny",
            )
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolNotFound(f"등록되지 않은 도구입니다: {call.name}")

        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # validate_tool_args()의 반환값을 validated에 대입합니다.
            validated = validate_tool_args(spec.json_schema, call.arguments)
        # ToolArgInvalid를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except ToolArgInvalid as error:
            # self._audit_denied()을 호출해 작업을 수행합니다.
            self._audit_denied(
                ctx,
                call_name=call.name,
                cause="arg_invalid",
                display=f"거부: {error.user_message}",
                tool_name=call.name,
                risk=spec.risk,
                capabilities=spec.capabilities,
                args_hash=None,
                normalized_args=None,
                decision="deny",
            )
            # 현재 예외를 다시 발생시켜 호출한 쪽으로 전달합니다.
            raise

        # ToolCall()의 반환값을 normalized_call에 대입합니다.
        normalized_call = ToolCall(id=call.id, name=call.name, arguments=validated)
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # self.gate.evaluate()의 반환값을 verdict에 대입합니다.
            verdict = self.gate.evaluate(normalized_call, ctx=ctx, spec=spec)
        # ApprovalRequired를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except ApprovalRequired as error:
            # 오른쪽 식을 계산한 값을 verdict_obj에 대입합니다.
            verdict_obj = error.verdict
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(verdict_obj, Verdict).
            if isinstance(verdict_obj, Verdict):
                # self._audit_denied()을 호출해 작업을 수행합니다.
                self._audit_denied(
                    ctx,
                    call_name=call.name,
                    cause="approval_required",
                    display=verdict_obj.display,
                    tool_name=call.name,
                    risk=verdict_obj.risk,
                    capabilities=verdict_obj.capabilities,
                    args_hash=verdict_obj.args_hash or None,
                    normalized_args=verdict_obj.normalized_args or None,
                    decision=verdict_obj.decision,
                )
            # 현재 예외를 다시 발생시켜 호출한 쪽으로 전달합니다.
            raise

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: verdict.decision == 'deny'.
        if verdict.decision == "deny":
            # self._audit_denied()을 호출해 작업을 수행합니다.
            self._audit_denied(
                ctx,
                call_name=call.name,
                cause="policy_denied",
                display=verdict.display,
                tool_name=call.name,
                risk=verdict.risk,
                capabilities=verdict.capabilities,
                args_hash=verdict.args_hash or None,
                normalized_args=verdict.normalized_args or None,
                decision="deny",
            )
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied(verdict.reason)

        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if verdict.decision in {"confirm", "typed_confirm"} and ticket is None:
            # self._audit_denied()을 호출해 작업을 수행합니다.
            self._audit_denied(
                ctx,
                call_name=call.name,
                cause="approval_required",
                display=verdict.display,
                tool_name=call.name,
                risk=verdict.risk,
                capabilities=verdict.capabilities,
                args_hash=verdict.args_hash,
                normalized_args=verdict.normalized_args,
                decision=verdict.decision,
            )
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ApprovalRequired(
                verdict.reason,
                {"tool_name": call.name, "args_hash": verdict.args_hash},
                verdict=verdict,
            )

        # consumed_ticket을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        consumed_ticket: ApprovalTicket | None = None
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ticket is not None.
        if ticket is not None:
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # self.approvals.consume()의 반환값을 consumed_ticket에 대입합니다.
                consumed_ticket = self.approvals.consume(
                    ticket.id,
                    tool_name=call.name,
                    args_hash=verdict.args_hash,
                    now=ctx.clock.now(),
                )
            # ApprovalMismatch를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
            except ApprovalMismatch as error:
                # self._audit_denied()을 호출해 작업을 수행합니다.
                self._audit_denied(
                    ctx,
                    call_name=call.name,
                    cause="approval_mismatch",
                    display=f"거부: {error.user_message}",
                    tool_name=call.name,
                    risk=verdict.risk,
                    capabilities=verdict.capabilities,
                    args_hash=verdict.args_hash,
                    normalized_args=verdict.normalized_args,
                    decision=verdict.decision,
                )
                # 현재 예외를 다시 발생시켜 호출한 쪽으로 전달합니다.
                raise

        # approval_payload을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        approval_payload = None
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: consumed_ticket is not None.
        if consumed_ticket is not None:
            # approval_payload에 딕셔너리(키와 값의 쌍)을 대입합니다.
            approval_payload = {
                "ticket_id": consumed_ticket.id,
                "method": consumed_ticket.granted_by,
                "channel": consumed_ticket.channel,
                "granted_at": consumed_ticket.granted_at.isoformat(timespec="milliseconds"),
            }

        # 열린 출력 대상에 데이터를 기록합니다.
        self.audit_writer.write(
            {
                "phase": "intent",
                "request_id": ctx.request_id,
                "session_id": ctx.session_id,
                "task_id": ctx.task_id,
                "step_no": None,
                "tool_name": call.name,
                "risk": verdict.risk,
                "decision": verdict.decision,
                "capabilities": sorted(verdict.capabilities),
                "args_hash": verdict.args_hash,
                "args_display": self._audit_text(verdict.display),
                "normalized_args": self._audit_args(verdict.normalized_args),
                "approval": approval_payload,
                "result": None,
            }
        )

        # ToolContext()의 반환값을 tctx에 대입합니다.
        tctx = ToolContext(
            ctx=ctx,
            sandbox=self.sandbox,
            ticket=consumed_ticket,
            normalized_args=verdict.normalized_args,
        )

        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._semaphore:
            # time.monotonic()의 반환값을 started에 대입합니다.
            started = time.monotonic()
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: spec.execution_mode ==
                # 'in_process'.
                if spec.execution_mode == "in_process":
                    # tool.run()의 반환값을 result에 대입합니다.
                    result = tool.run(validated, tctx)
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: spec.execution_mode ==
                # 'detached_allowlisted'.
                elif spec.execution_mode == "detached_allowlisted":
                    # self._run_detached()의 반환값을 result에 대입합니다.
                    result = self._run_detached(tool, validated, tctx, spec.timeout_s)
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: spec.execution_mode ==
                # 'managed_process'.
                elif spec.execution_mode == "managed_process":
                    # self._run_managed()의 반환값을 result에 대입합니다.
                    result = self._run_managed(tool, validated, tctx, spec.timeout_s)
                # 앞선 조건이 거짓이면 이 블록을 실행합니다.
                else:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise ToolError(f"지원하지 않는 execution_mode: {spec.execution_mode}")
            # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
            except Exception as error:
                # max()의 반환값을 duration_ms에 대입합니다.
                duration_ms = max(0, int((time.monotonic() - started) * 1000))
                # getattr()의 반환값을 message에 대입합니다.
                message = getattr(error, "user_message", str(error))
                # ToolResult()의 반환값을 result에 대입합니다.
                result = ToolResult(
                    ok=False,
                    output=message,
                    data=None,
                    error=message,
                    changed_paths=(),
                    duration_ms=duration_ms,
                    truncated=False,
                    untrusted=spec.untrusted_output,
                )

        # 열린 출력 대상에 데이터를 기록합니다.
        self.audit_writer.write(
            {
                "phase": "result",
                "request_id": ctx.request_id,
                "session_id": ctx.session_id,
                "task_id": ctx.task_id,
                "step_no": None,
                "tool_name": call.name,
                "risk": verdict.risk,
                "decision": verdict.decision,
                "capabilities": sorted(verdict.capabilities),
                "args_hash": verdict.args_hash,
                "args_display": self._audit_text(verdict.display),
                "normalized_args": self._audit_args(verdict.normalized_args),
                "approval": approval_payload,
                "result": {
                    "ok": result.ok,
                    "error": self._audit_text(result.error) if result.error else None,
                    "duration_ms": result.duration_ms,
                    "changed_paths": list(result.changed_paths),
                    "truncated": result.truncated,
                    "exit_code": 0 if result.ok else 1,
                },
            }
        )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return result

    # _audit_denied(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: ctx, call_name, cause, display, tool_name, risk, capabilities, args_hash,
    # normalized_args, decision.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _audit_denied(
        self,
        ctx: RequestContext,
        *,
        call_name: str,
        cause: AuditCause,
        display: str,
        tool_name: str,
        risk: str | None,
        capabilities: frozenset[str] | None,
        args_hash: str | None,
        normalized_args: dict[str, Any] | None,
        decision: str,
    ) -> None:
        # 열린 출력 대상에 데이터를 기록합니다.
        self.audit_writer.write(
            {
                "phase": "denied",
                "request_id": ctx.request_id,
                "session_id": ctx.session_id,
                "task_id": ctx.task_id,
                "step_no": None,
                "tool_name": tool_name,
                "risk": risk,
                "decision": decision,
                "cause": cause,
                "capabilities": sorted(capabilities) if capabilities else None,
                "args_hash": args_hash,
                "args_display": self._audit_text(display),
                "normalized_args": self._audit_args(normalized_args),
                "approval": None,
                "result": None,
            }
        )

    # _audit_text(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: value.
    # 반환 타입 힌트: 문자열(str).
    def _audit_text(self, value: str) -> str:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.privacy.for_log(value)

    # _audit_args(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: value.
    # 반환 타입 힌트: dict[str, Any] | None.
    def _audit_args(self, value: dict[str, Any] | None) -> dict[str, Any] | None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: value is None.
        if value is None:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None

        # sanitize(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # 입력: item, key.
        # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
        # 반환 타입 힌트: 어떤 타입이든 허용(Any).
        def sanitize(item: Any, *, key: str | None = None) -> Any:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: key == 'path'.
            if key == "path":
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return item
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(item, str).
            if isinstance(item, str):
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return self.privacy.for_log(item)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(item, dict).
            if isinstance(item, dict):
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
                return {
                    str(name): sanitize(nested, key=str(name))
                    for name, nested in item.items()
                }
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(item, list).
            if isinstance(item, list):
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
                return [sanitize(nested) for nested in item]
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(item, tuple).
            if isinstance(item, tuple):
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
                return [sanitize(nested) for nested in item]
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return item

        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return cast(dict[str, Any], sanitize(value))

    # _run_detached(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: tool, args, tctx, timeout_s.
    # 반환 타입 힌트: ToolResult.
    def _run_detached(
        self,
        tool: Any,
        args: dict[str, Any],
        tctx: ToolContext,
        timeout_s: float,
    ) -> ToolResult:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del timeout_s
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return cast(ToolResult, tool.run(args, tctx))

    # _run_managed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: tool, args, tctx, timeout_s.
    # 반환 타입 힌트: ToolResult.
    def _run_managed(
        self,
        tool: Any,
        args: dict[str, Any],
        tctx: ToolContext,
        timeout_s: float,
    ) -> ToolResult:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: os.name != 'nt'.
        if os.name != "nt":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return cast(ToolResult, tool.run(args, tctx))
        # getattr()의 반환값을 command에 대입합니다.
        command = getattr(tool, "managed_command", None)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: command is None.
        if command is None:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return cast(ToolResult, tool.run(args, tctx))
        # _minimal_env()의 반환값을 env에 대입합니다.
        env = _minimal_env(self.env_allowlist)
        # 오른쪽 식을 계산한 값을 deadline에 대입합니다.
        deadline = timeout_s or self.default_timeout_s
        # subprocess.Popen()의 반환값을 proc에 대입합니다.
        proc = subprocess.Popen(
            command(args, tctx),
            shell=False,
            cwd=str(self.sandbox.data_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        # 오른쪽 식을 계산한 값을 job에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        job = _assign_job_object(proc.pid) if os.name == "nt" else None
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # 언패킹: 오른쪽 결과를 순서대로 (stdout, stderr)에 나누어 담습니다.
            stdout, stderr = proc.communicate(timeout=deadline)
        # subprocess.TimeoutExpired를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
        # 담깁니다.
        except subprocess.TimeoutExpired as error:
            # _kill_process_tree()을 호출해 작업을 수행합니다.
            _kill_process_tree(proc.pid, job)
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolTimeout("도구 실행 시간이 초과되었습니다.") from error
        # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
        finally:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: job is not None.
            if job is not None:
                # _close_job()을 호출해 작업을 수행합니다.
                _close_job(job)
        # 아래 함수()의 반환값을 output에 대입합니다.
        output = (stdout or b"")[: self.max_output_bytes].decode("utf-8", errors="replace")
        # 오른쪽 식을 계산한 값을 ok에 대입합니다.
        ok = proc.returncode == 0
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ToolResult(
            ok=ok,
            output=output or (stderr or b"").decode("utf-8", errors="replace"),
            data={"exit_code": proc.returncode},
            error=None if ok else f"exit code {proc.returncode}",
            changed_paths=(),
            duration_ms=0,
            truncated=len(stdout or b"") > self.max_output_bytes,
            untrusted=False,
        )


# _minimal_env(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: allowlist.
# 반환 타입 힌트: dict[str, str].
def _minimal_env(allowlist: tuple[str, ...]) -> dict[str, str]:
    # env에 딕셔너리(키와 값의 쌍)을 대입합니다.
    env: dict[str, str] = {}
    # for 반복문: 대상의 항목을 하나씩 key에 대입하며 아래 블록을 실행합니다.
    for key in allowlist:
        # os.environ.get()의 반환값을 value에 대입합니다.
        value = os.environ.get(key)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: value is not None.
        if value is not None:
            # 오른쪽 식을 계산한 값을 env[key]에 대입합니다.
            env[key] = value
    # env.setdefault()을 호출해 작업을 수행합니다.
    env.setdefault("SystemRoot", os.environ.get("SYSTEMROOT", r"C:\Windows"))
    # env['PATH']에 문자열을 대입합니다.
    env["PATH"] = ""
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return env


# _assign_job_object(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: pid.
# 반환 타입 힌트: int | None.
def _assign_job_object(pid: int) -> int | None:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        import ctypes

        # 오른쪽 식을 계산한 값을 kernel32에 대입합니다.
        kernel32 = ctypes.windll.kernel32
        # kernel32.CreateJobObjectW()의 반환값을 job에 대입합니다.
        job = kernel32.CreateJobObjectW(None, None)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not job.
        if not job:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None
        # ctypes.c_ulong()의 반환값을 info에 대입합니다.
        info = ctypes.c_ulong(0x2000)
        # kernel32.SetInformationJobObject()을 호출해 작업을 수행합니다.
        kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        # kernel32.OpenProcess()의 반환값을 handle에 대입합니다.
        handle = kernel32.OpenProcess(0x001F0FFF, False, pid)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: handle.
        if handle:
            # kernel32.AssignProcessToJobObject()을 호출해 작업을 수행합니다.
            kernel32.AssignProcessToJobObject(job, handle)
            # kernel32.CloseHandle()을 호출해 작업을 수행합니다.
            kernel32.CloseHandle(handle)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return cast(int, job)
    # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except Exception:
        # None을 반환하고 이 함수의 실행을 끝냅니다.
        return None


# _close_job(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: job.
# 반환 타입 힌트: 별도 결과 없음(None).
def _close_job(job: int) -> None:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        import ctypes

        # ctypes.windll.kernel32.CloseHandle()을 호출해 작업을 수행합니다.
        ctypes.windll.kernel32.CloseHandle(job)
    # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except Exception:
        # 문법상 블록은 필요하지만 여기서는 아무 작업도 하지 않습니다.
        pass


# _kill_process_tree(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: pid, job.
# 반환 타입 힌트: 별도 결과 없음(None).
def _kill_process_tree(pid: int, job: int | None) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: job is not None.
    if job is not None:
        # _close_job()을 호출해 작업을 수행합니다.
        _close_job(job)
        # 이 함수를 여기서 끝냅니다. 값을 쓰지 않은 return은 None을 반환합니다.
        return
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with suppress(Exception):
        # subprocess.run()을 호출해 작업을 수행합니다.
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

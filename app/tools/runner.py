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

AuditCause = str


@dataclass
class ToolRunner:
    registry: ToolRegistry
    gate: SafetyGate
    approvals: ApprovalStore
    audit_writer: JsonlAuditWriter
    sandbox: Sandbox
    max_concurrent: int
    max_output_bytes: int
    env_allowlist: tuple[str, ...]
    default_timeout_s: float
    privacy: PrivacyGate
    _semaphore: threading.Semaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._semaphore = threading.Semaphore(self.max_concurrent)

    def execute(
        self,
        call: ToolCall,
        *,
        ctx: RequestContext,
        ticket: ApprovalTicket | None = None,
    ) -> ToolResult:
        spec = self.registry.specs.get(call.name)
        tool = self.registry.tools.get(call.name)
        if spec is None or tool is None or not spec.enabled:
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
            raise ToolNotFound(f"등록되지 않은 도구입니다: {call.name}")

        try:
            validated = validate_tool_args(spec.json_schema, call.arguments)
        except ToolArgInvalid as error:
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
            raise

        normalized_call = ToolCall(id=call.id, name=call.name, arguments=validated)
        try:
            verdict = self.gate.evaluate(normalized_call, ctx=ctx, spec=spec)
        except ApprovalRequired as error:
            verdict_obj = error.verdict
            if isinstance(verdict_obj, Verdict):
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
            raise

        if verdict.decision == "deny":
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
            raise PolicyDenied(verdict.reason)

        if verdict.decision in {"confirm", "typed_confirm"} and ticket is None:
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
            raise ApprovalRequired(
                verdict.reason,
                {"tool_name": call.name, "args_hash": verdict.args_hash},
                verdict=verdict,
            )

        consumed_ticket: ApprovalTicket | None = None
        if ticket is not None:
            try:
                consumed_ticket = self.approvals.consume(
                    ticket.id,
                    tool_name=call.name,
                    args_hash=verdict.args_hash,
                    now=ctx.clock.now(),
                )
            except ApprovalMismatch as error:
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
                raise

        approval_payload = None
        if consumed_ticket is not None:
            approval_payload = {
                "ticket_id": consumed_ticket.id,
                "method": consumed_ticket.granted_by,
                "channel": consumed_ticket.channel,
                "granted_at": consumed_ticket.granted_at.isoformat(timespec="milliseconds"),
            }

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

        tctx = ToolContext(
            ctx=ctx,
            sandbox=self.sandbox,
            ticket=consumed_ticket,
            normalized_args=verdict.normalized_args,
        )

        with self._semaphore:
            started = time.monotonic()
            try:
                if spec.execution_mode == "in_process":
                    result = tool.run(validated, tctx)
                elif spec.execution_mode == "detached_allowlisted":
                    result = self._run_detached(tool, validated, tctx, spec.timeout_s)
                elif spec.execution_mode == "managed_process":
                    result = self._run_managed(tool, validated, tctx, spec.timeout_s)
                else:
                    raise ToolError(f"지원하지 않는 execution_mode: {spec.execution_mode}")
            except Exception as error:
                duration_ms = max(0, int((time.monotonic() - started) * 1000))
                message = getattr(error, "user_message", str(error))
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
        return result

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

    def _audit_text(self, value: str) -> str:
        return self.privacy.for_log(value)

    def _audit_args(self, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None

        def sanitize(item: Any, *, key: str | None = None) -> Any:
            if key == "path":
                return item
            if isinstance(item, str):
                return self.privacy.for_log(item)
            if isinstance(item, dict):
                return {
                    str(name): sanitize(nested, key=str(name))
                    for name, nested in item.items()
                }
            if isinstance(item, list):
                return [sanitize(nested) for nested in item]
            if isinstance(item, tuple):
                return [sanitize(nested) for nested in item]
            return item

        return cast(dict[str, Any], sanitize(value))

    def _run_detached(
        self,
        tool: Any,
        args: dict[str, Any],
        tctx: ToolContext,
        timeout_s: float,
    ) -> ToolResult:
        del timeout_s
        return cast(ToolResult, tool.run(args, tctx))

    def _run_managed(
        self,
        tool: Any,
        args: dict[str, Any],
        tctx: ToolContext,
        timeout_s: float,
    ) -> ToolResult:
        if os.name != "nt":
            return cast(ToolResult, tool.run(args, tctx))
        command = getattr(tool, "managed_command", None)
        if command is None:
            return cast(ToolResult, tool.run(args, tctx))
        env = _minimal_env(self.env_allowlist)
        deadline = timeout_s or self.default_timeout_s
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
        job = _assign_job_object(proc.pid) if os.name == "nt" else None
        try:
            stdout, stderr = proc.communicate(timeout=deadline)
        except subprocess.TimeoutExpired as error:
            _kill_process_tree(proc.pid, job)
            raise ToolTimeout("도구 실행 시간이 초과되었습니다.") from error
        finally:
            if job is not None:
                _close_job(job)
        output = (stdout or b"")[: self.max_output_bytes].decode("utf-8", errors="replace")
        ok = proc.returncode == 0
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


def _minimal_env(allowlist: tuple[str, ...]) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in allowlist:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    env.setdefault("SystemRoot", os.environ.get("SYSTEMROOT", r"C:\Windows"))
    env["PATH"] = ""
    return env


def _assign_job_object(pid: int) -> int | None:
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = ctypes.c_ulong(0x2000)
        kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        handle = kernel32.OpenProcess(0x001F0FFF, False, pid)
        if handle:
            kernel32.AssignProcessToJobObject(job, handle)
            kernel32.CloseHandle(handle)
        return cast(int, job)
    except Exception:
        return None


def _close_job(job: int) -> None:
    try:
        import ctypes

        ctypes.windll.kernel32.CloseHandle(job)
    except Exception:
        pass


def _kill_process_tree(pid: int, job: int | None) -> None:
    if job is not None:
        _close_job(job)
        return
    with suppress(Exception):
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

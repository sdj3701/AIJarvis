"""Multi-step agent loop: Decide → Validate → Act → Observe → Final."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Literal

from app.budget import BudgetGuard, estimate_llm_cost
from app.config.models import Settings
from app.core.context import RequestContext
from app.core.errors import ApprovalRequired, JarvisError, LLMBadResponse, PolicyDenied
from app.llm.base import LLMClient, LLMUsage, Message, ToolCall
from app.orchestrator.envelope import wrap_untrusted_content
from app.orchestrator.prompt import PromptAssembler
from app.orchestrator.research import load_tools_prompt
from app.orchestrator.tasks import (
    CachedStepResult,
    StepRecord,
    StepState,
    TaskState,
    TaskStore,
    idempotency_key,
)
from app.safety.approval import ApprovalTicket
from app.safety.gate import SafetyGate, Verdict
from app.tools.base import ToolResult, ToolSpec
from app.tools.registry import ToolRegistry, validate_tool_args
from app.tools.runner import ToolRunner

_SIDE_EFFECT_TOOLS = frozenset(
    {"create_file", "open_app", "open_folder", "open_url", "run_skill"}
)
_NEVER_AUTO_RETRY = frozenset({"open_app", "open_folder", "create_file", "run_skill", "open_url"})

_GOAL_PATTERNS: dict[str, tuple[str, ...]] = {
    "create_file": ("저장", "파일", "notes", "메모", "write", "save", "만들", "작성"),
    "open_folder": ("폴더", "folder", "디렉", "열어"),
    "open_app": ("앱", "app", "실행", "메모장", "계산기"),
    "open_url": ("url", "링크", "link", "사이트", "웹페이지"),
    "run_skill": ("스크립트", "skill", "스킬"),
}


@dataclass(frozen=True, slots=True)
class AgentStopReason:
    reason: Literal[
        "final",
        "max_steps",
        "task_timeout",
        "step_timeout",
        "approval_pending",
        "error",
        "cancelled",
    ]
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class AgentResult:
    ok: bool
    text: str
    task_id: str
    steps: tuple[StepRecord, ...]
    stop: AgentStopReason
    usage: LLMUsage
    pending_approval: Verdict | None = None
    pending_tool_call: ToolCall | None = None
    pending_step_no: int | None = None


_AGENT_GOAL_SIDE_EFFECT = ("저장", "notes", "폴더", "파일", "열어", "만들")
_AGENT_GOAL_SEARCH = ("검색", "찾아", "조사", "알려")


def should_run_agent_goal(text: str) -> bool:
    """Detect multi-step goals that should use the agent loop, not research auto-path."""
    stripped = text.strip()
    if not stripped:
        return False
    has_search = any(marker in stripped for marker in _AGENT_GOAL_SEARCH)
    has_side_effect = any(marker in stripped for marker in _AGENT_GOAL_SIDE_EFFECT)
    return has_search and has_side_effect


def goal_permits_side_effect(goal: str, tool_name: str) -> bool:
    if tool_name not in _SIDE_EFFECT_TOOLS:
        return True
    patterns = _GOAL_PATTERNS.get(tool_name, ())
    lowered = goal.lower()
    return any(pattern in lowered or pattern in goal for pattern in patterns)


def format_step_breakdown(steps: Sequence[StepRecord], *, max_steps: int) -> str:
    completed = [str(s.step_no) + "." + s.tool_name for s in steps if s.state == "succeeded"]
    failed = [str(s.step_no) + "." + s.tool_name for s in steps if s.state == "failed"]
    cancelled = [str(s.step_no) + "." + s.tool_name for s in steps if s.state == "cancelled"]
    executed = {s.step_no for s in steps}
    not_run = [
        str(number)
        for number in range(1, max_steps + 1)
        if number not in executed
    ]
    lines = ["## 단계 현황"]
    lines.append("완료: " + (", ".join(completed) if completed else "없음"))
    lines.append("실패: " + (", ".join(failed) if failed else "없음"))
    if cancelled:
        lines.append("취소: " + ", ".join(cancelled))
    lines.append("미실행: " + (", ".join(not_run) if not_run else "없음"))
    return "\n".join(lines)


class AgentRunner:
    """Execute bounded multi-step tool loops with task persistence."""

    def __init__(
        self,
        *,
        settings: Settings,
        llm: LLMClient,
        tasks: TaskStore,
        tool_runner: ToolRunner,
        safety_gate: SafetyGate,
        registry: ToolRegistry,
        budget: BudgetGuard,
        prompt: PromptAssembler,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._tasks = tasks
        self._tool_runner = tool_runner
        self._safety_gate = safety_gate
        self._registry = registry
        self._budget = budget
        self._prompt = prompt

    def run(
        self,
        *,
        goal: str,
        ctx: RequestContext,
        task_id: str,
        initial_response_tool_call: ToolCall | None = None,
        resume_step_no: int | None = None,
        resume_ticket: ApprovalTicket | None = None,
    ) -> AgentResult:
        agent_cfg = self._settings.agent
        now = ctx.clock.now()
        run_started_ms = ctx.clock.monotonic_ms()
        task = self._tasks.get_task(task_id)
        if task is None:
            raise ValueError(f"unknown task: {task_id}")

        self._tasks.update_task_state(task_id, "running", now=now)
        ctx = replace(ctx, task_id=task_id)

        observations: list[Message] = []
        usage_total = LLMUsage(0, 0, Decimal("0"), 0)
        step_no = resume_step_no or (len(self._tasks.list_steps(task_id)) + 1)
        pending_call = initial_response_tool_call
        stop = AgentStopReason("final")

        while step_no <= agent_cfg.max_steps:
            elapsed_s = _elapsed_seconds(ctx, run_started_ms)
            if elapsed_s >= agent_cfg.total_timeout_s:
                stop = AgentStopReason("task_timeout", "전체 작업 시간이 초과되었습니다.")
                self._tasks.update_task_state(task_id, "failed", now=ctx.clock.now())
                break
            step_started_ms = ctx.clock.monotonic_ms()
            step_limit_s = min(
                agent_cfg.step_timeout_s,
                max(0.001, agent_cfg.total_timeout_s - elapsed_s),
            )

            if pending_call is None:
                response = self._decide(
                    goal,
                    observations,
                    ctx=ctx,
                    timeout_s=min(self._settings.llm.timeout_s, step_limit_s),
                )
                usage_total = _merge_usage(usage_total, response.usage)
                if _elapsed_seconds(ctx, step_started_ms) >= step_limit_s:
                    stop = AgentStopReason("step_timeout", "단계 실행 시간이 초과되었습니다.")
                    self._tasks.update_task_state(task_id, "failed", now=ctx.clock.now())
                    break
                if response.tool_calls:
                    if len(response.tool_calls) > 1:
                        pending_call = response.tool_calls[0]
                    else:
                        pending_call = response.tool_calls[0]
                elif response.text is not None:
                    final_text = response.text
                    steps = self._tasks.list_steps(task_id)
                    breakdown = format_step_breakdown(steps, max_steps=agent_cfg.max_steps)
                    self._tasks.update_task_state(task_id, "succeeded", now=ctx.clock.now())
                    self._emit_stop(ctx, task_id, "final", steps)
                    return AgentResult(
                        ok=True,
                        text=f"{final_text}\n\n{breakdown}",
                        task_id=task_id,
                        steps=steps,
                        stop=AgentStopReason("final"),
                        usage=usage_total,
                    )
                else:
                    raise LLMBadResponse("LLM 응답 본문이 없습니다.")

            call = pending_call
            pending_call = None

            try:
                outcome = self._execute_step(
                    call,
                    step_no=step_no,
                    goal=goal,
                    ctx=ctx,
                    ticket=resume_ticket if step_no == resume_step_no else None,
                )
                resume_ticket = None
            except ApprovalRequired as error:
                verdict = error.verdict
                if not isinstance(verdict, Verdict):
                    raise
                self._tasks.update_task_state(task_id, "running", now=ctx.clock.now())
                steps = self._tasks.list_steps(task_id)
                self._emit_stop(ctx, task_id, "approval_pending", steps)
                return AgentResult(
                    ok=False,
                    text=verdict.display,
                    task_id=task_id,
                    steps=steps,
                    stop=AgentStopReason("approval_pending"),
                    usage=usage_total,
                    pending_approval=verdict,
                    pending_tool_call=call,
                    pending_step_no=step_no,
                )
            except (PolicyDenied, JarvisError) as error:
                message = error.user_message if isinstance(error, JarvisError) else str(error)
                self._tasks.mark_step_finished(
                    task_id,
                    step_no,
                    state="failed",
                    result_summary=message,
                    changed_paths=(),
                    now=ctx.clock.now(),
                )
                stop = AgentStopReason("error", message)
                self._tasks.update_task_state(task_id, "failed", now=ctx.clock.now())
                break

            if not outcome.ok:
                stop = AgentStopReason("error", outcome.error)
                self._tasks.update_task_state(task_id, "failed", now=ctx.clock.now())
                break
            if _elapsed_seconds(ctx, step_started_ms) >= step_limit_s:
                stop = AgentStopReason("step_timeout", "단계 실행 시간이 초과되었습니다.")
                self._tasks.update_task_state(task_id, "failed", now=ctx.clock.now())
                break

            observations.append(Message("assistant", f"[step {step_no}] {call.name}"))
            observe_text = self._observe(outcome, call=call, ctx=ctx)
            observations.append(
                Message("tool", observe_text, tool_call_id=call.id, name=call.name)
            )
            ctx.events.emit(
                "agent.step",
                {
                    "task_id": task_id,
                    "step_no": step_no,
                    "decision": "tool",
                    "tool_name": call.name,
                },
            )
            step_no += 1

        if stop.reason == "final" and step_no > agent_cfg.max_steps:
            stop = AgentStopReason("max_steps", f"최대 {agent_cfg.max_steps}단계에 도달했습니다.")

        steps = self._tasks.list_steps(task_id)
        final_state: TaskState = "cancelled" if stop.reason == "cancelled" else "failed"
        if stop.reason in {"max_steps", "task_timeout"}:
            final_state = "failed"
        self._tasks.update_task_state(task_id, final_state, now=ctx.clock.now())
        breakdown = format_step_breakdown(steps, max_steps=agent_cfg.max_steps)
        detail = stop.detail or "작업이 중단되었습니다."
        self._emit_stop(ctx, task_id, stop.reason, steps)
        return AgentResult(
            ok=False,
            text=f"{detail}\n\n{breakdown}",
            task_id=task_id,
            steps=steps,
            stop=stop,
            usage=usage_total,
        )

    def _decide(
        self,
        goal: str,
        observations: Sequence[Message],
        *,
        ctx: RequestContext,
        timeout_s: float,
    ) -> Any:
        estimated = estimate_llm_cost(
            self._settings.llm,
            prompt_tokens=self._settings.llm.context.max_input_tokens,
            max_output_tokens=self._settings.llm.max_output_tokens,
        )
        self._budget.check("llm", estimated, ctx=ctx)
        tools_prompt = load_tools_prompt()
        agent_instruction = (
            f"사용자 목표: {goal}\n"
            "한 번에 하나의 도구만 호출하거나, 모든 단계가 끝났으면 최종 답변을 작성하세요."
        )
        if observations:
            lines = [agent_instruction, "", "이전 단계 관찰:"]
            for message in observations:
                if message.role == "assistant":
                    lines.append(message.content)
                elif message.role == "tool":
                    label = message.name or "tool"
                    lines.append(f"[{label} 결과]\n{message.content}")
            agent_instruction = "\n".join(lines)
        plan = self._prompt.build(
            current_user_text=agent_instruction,
            history=(),
            cancel=ctx.cancel,
            extra_system=(tools_prompt,),
        )
        tool_specs = self._registry.llm_tool_specs()
        response = self._llm.complete(
            messages=plan.messages,
            tools=tool_specs,
            timeout_s=timeout_s,
            ctx=ctx,
            temperature=self._settings.llm.temperature,
            max_output_tokens=self._settings.llm.max_output_tokens,
        )
        self._budget.record_llm(response.usage, ctx=ctx)
        return response

    def _execute_step(
        self,
        call: ToolCall,
        *,
        step_no: int,
        goal: str,
        ctx: RequestContext,
        ticket: ApprovalTicket | None,
    ) -> ToolResult:
        spec = self._registry.specs.get(call.name)
        if spec is None or not spec.enabled:
            raise PolicyDenied(f"등록되지 않은 도구입니다: {call.name}")

        validated = validate_tool_args(spec.json_schema, call.arguments)
        normalized_call = ToolCall(id=call.id, name=call.name, arguments=validated)
        verdict = self._safety_gate.evaluate(normalized_call, ctx=ctx, spec=spec)

        if call.name in _SIDE_EFFECT_TOOLS and not goal_permits_side_effect(goal, call.name):
            raise PolicyDenied(
                "외부 콘텐츠나 모델 제안만으로는 부작용 도구를 실행하지 않습니다. "
                "원래 사용자 요청에 해당 작업이 포함되어야 합니다."
            )

        key = idempotency_key(
            task_id=ctx.task_id or "",
            step_no=step_no,
            tool_name=call.name,
            args_hash=verdict.args_hash,
        )
        cached = self._tasks.get_succeeded_by_idempotency(key)
        if cached is None and ctx.task_id:
            prior = self._tasks.find_succeeded_step(
                ctx.task_id,
                call.name,
                verdict.args_hash,
            )
            if prior is not None and prior.result_summary is not None:
                cached = CachedStepResult(
                    ok=True,
                    output=prior.result_summary,
                    changed_paths=prior.changed_paths,
                    error=None,
                )
        if cached is not None:
            self._ensure_step_record(
                ctx.task_id or "",
                step_no,
                call.name,
                verdict,
                cached,
                ctx=ctx,
            )
            return ToolResult(
                ok=cached.ok,
                output=cached.output,
                data=None,
                error=cached.error,
                changed_paths=cached.changed_paths,
                duration_ms=0,
                truncated=False,
                untrusted=spec.untrusted_output,
            )

        existing = self._tasks.get_step(ctx.task_id or "", step_no)
        if existing is None:
            self._tasks.create_step(
                task_id=ctx.task_id or "",
                step_no=step_no,
                tool_name=call.name,
                normalized_args=verdict.normalized_args,
            )
        elif existing.args_hash != verdict.args_hash:
            raise PolicyDenied("승인된 단계와 도구 인자가 일치하지 않습니다.")

        if verdict.decision in {"confirm", "typed_confirm"} and ticket is None:
            # ToolRunner가 승인 요청 감사 로그를 남긴 뒤 ApprovalRequired를 올린다.
            # 실제 실행 전이므로 step은 pending 상태를 유지한다.
            return self._run_with_retry(normalized_call, spec=spec, ctx=ctx, ticket=None)

        self._tasks.mark_step_running(ctx.task_id or "", step_no, now=ctx.clock.now())
        result = self._run_with_retry(normalized_call, spec=spec, ctx=ctx, ticket=ticket)
        state: StepState = "succeeded" if result.ok else "failed"
        self._tasks.mark_step_finished(
            ctx.task_id or "",
            step_no,
            state=state,
            result_summary=result.output[:2000],
            changed_paths=result.changed_paths,
            now=ctx.clock.now(),
        )
        ctx.events.emit(
            "tool.result",
            {
                "tool_name": call.name,
                "args_hash": verdict.args_hash,
                "ok": result.ok,
                "duration_ms": result.duration_ms,
                "changed_paths": list(result.changed_paths),
                "truncated": result.truncated,
                "error": result.error,
            },
        )
        return result

    def _ensure_step_record(
        self,
        task_id: str,
        step_no: int,
        tool_name: str,
        verdict: Verdict,
        cached: CachedStepResult,
        *,
        ctx: RequestContext,
    ) -> None:
        existing = self._tasks.get_step(task_id, step_no)
        if existing is not None and existing.state == "succeeded":
            return
        if existing is None:
            self._tasks.create_step(
                task_id=task_id,
                step_no=step_no,
                tool_name=tool_name,
                normalized_args=verdict.normalized_args,
            )
        self._tasks.mark_step_running(task_id, step_no, now=ctx.clock.now())
        self._tasks.mark_step_finished(
            task_id,
            step_no,
            state="succeeded",
            result_summary=cached.output[:2000],
            changed_paths=cached.changed_paths,
            now=ctx.clock.now(),
        )

    def _run_with_retry(
        self,
        call: ToolCall,
        *,
        spec: ToolSpec,
        ctx: RequestContext,
        ticket: ApprovalTicket | None,
    ) -> ToolResult:
        max_retries = 0
        if call.name in {"web_search", "doc_search"} and spec.idempotent:
            max_retries = self._settings.agent.auto_retry_idempotent
        elif call.name == "fetch_url" and spec.idempotent:
            max_retries = 1

        if call.name in _NEVER_AUTO_RETRY:
            max_retries = 0

        attempts = 0
        last: ToolResult | None = None
        while attempts <= max_retries:
            try:
                result = self._tool_runner.execute(
                    call,
                    ctx=ctx,
                    ticket=ticket if attempts == 0 else None,
                )
                if result.ok or call.name not in {"web_search", "doc_search", "fetch_url"}:
                    return result
                if call.name == "fetch_url" and not _is_transient_network(result.error):
                    return result
                last = result
            except ApprovalRequired:
                raise
            except JarvisError as error:
                if call.name == "fetch_url" and _is_transient_network(error.user_message):
                    last = ToolResult(
                        ok=False,
                        output=error.user_message,
                        data=None,
                        error=error.user_message,
                        changed_paths=(),
                        duration_ms=0,
                        truncated=False,
                        untrusted=True,
                    )
                else:
                    raise
            attempts += 1
            ticket = None
        return last or ToolResult(
            ok=False,
            output="도구 실행에 실패했습니다.",
            data=None,
            error="retry_exhausted",
            changed_paths=(),
            duration_ms=0,
            truncated=False,
            untrusted=spec.untrusted_output,
        )

    def _observe(self, result: ToolResult, *, call: ToolCall, ctx: RequestContext) -> str:
        if not result.untrusted:
            return result.output
        return wrap_untrusted_content(
            source=call.name,
            source_kind="tool_output",
            fetched_at=ctx.clock.now(),
            body=result.output,
        )

    def _emit_stop(
        self,
        ctx: RequestContext,
        task_id: str,
        reason: str,
        steps: Sequence[StepRecord],
    ) -> None:
        ctx.events.emit(
            "agent.stop",
            {
                "task_id": task_id,
                "reason": reason,
                "steps": [
                    {
                        "step_no": step.step_no,
                        "tool_name": step.tool_name,
                        "state": step.state,
                    }
                    for step in steps
                ],
            },
        )


def _merge_usage(total: LLMUsage, addition: LLMUsage) -> LLMUsage:
    return LLMUsage(
        prompt_tokens=total.prompt_tokens + addition.prompt_tokens,
        completion_tokens=total.completion_tokens + addition.completion_tokens,
        cost_usd=total.cost_usd + addition.cost_usd,
        latency_ms=total.latency_ms + addition.latency_ms,
    )


def _elapsed_seconds(ctx: RequestContext, started_ms: int) -> float:
    return max(0.0, (ctx.clock.monotonic_ms() - started_ms) / 1000)


def _is_transient_network(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.lower()
    markers = ("timeout", "timed out", "connection", "network", "일시", "연결")
    return any(marker in lowered for marker in markers)

"""Phase 1 turn orchestration with write-ahead user input durability."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from app.budget import BudgetGuard, BudgetStatus, estimate_llm_cost
from app.config.models import Settings
from app.core.clock import Clock, RandomSource, Sleeper
from app.core.context import AuditWriter, CancellationToken, RequestContext
from app.core.errors import ApprovalRequired, JarvisError, LLMBadResponse
from app.core.ids import PrefixedIdFactory
from app.core.test_hooks import CrashTestHook
from app.llm.base import LLMClient, Message, ToolCall
from app.memory.commands import MemoryCommandContext
from app.memory.models import MemoryQuery
from app.memory.retrieval import trim_memory_for_budget
from app.memory.store import Channel, EndReason, RawRecord, SQLiteSessionStore
from app.memory.summarizer import SessionSummarizer
from app.orchestrator.agent import AgentResult, AgentRunner, should_run_agent_goal
from app.orchestrator.prompt import PromptAssembler
from app.orchestrator.research import (
    ResearchRunner,
    build_research_context,
    enforce_research_status,
    load_tools_prompt,
    parse_search_command,
    run_index,
    should_auto_search,
)
from app.orchestrator.tasks import StepRecord, TaskStore
from app.orchestrator.tool_commands import parse_tool_command
from app.privacy.gate import PrivacyGate
from app.rag.indexer import DocumentIndexer
from app.safety.approval import ApprovalStore, ApprovalTicket
from app.safety.gate import SafetyGate, Verdict
from app.telemetry.events import EventIdentity
from app.telemetry.masking import LogMasker
from app.telemetry.metrics import SQLiteMetrics
from app.tools.runner import ToolRunner


class IdentityEventSink(Protocol):
    def emit(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        identity: EventIdentity | None = None,
    ) -> None: ...


class BoundEventWriter:
    def __init__(
        self,
        sink: IdentityEventSink,
        identity: EventIdentity,
        *,
        after_emit: Callable[[str], None] | None = None,
    ) -> None:
        self._sink = sink
        self._identity = identity
        self._after_emit = after_emit

    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        self._sink.emit(event_type, payload, identity=self._identity)
        if self._after_emit is not None:
            self._after_emit(event_type)


class NullAuditWriter:
    def write(self, record: Mapping[str, Any]) -> None:
        del record


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    ok: bool
    text: str
    request_id: str
    turn_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    pending_approval: Verdict | None = None
    pending_tool_call: ToolCall | None = None
    task_id: str | None = None
    steps: tuple[StepRecord, ...] = ()


class ChatOrchestrator:
    """Own one CLI session and preserve ordering across storage, events, and LLM."""

    def __init__(
        self,
        *,
        settings: Settings,
        llm: LLMClient,
        sessions: SQLiteSessionStore,
        budget: BudgetGuard,
        masker: LogMasker,
        events: IdentityEventSink,
        clock: Clock,
        sleeper: Sleeper,
        random: RandomSource,
        ids: PrefixedIdFactory,
        verify_model: Callable[[], object] | None = None,
        test_hook: CrashTestHook | None = None,
        metrics: SQLiteMetrics | None = None,
        summarizer: SessionSummarizer | None = None,
        indexer: DocumentIndexer | None = None,
        research: ResearchRunner | None = None,
        tool_runner: ToolRunner | None = None,
        safety_gate: SafetyGate | None = None,
        approval_store: ApprovalStore | None = None,
        audit_writer: AuditWriter | None = None,
        task_store: TaskStore | None = None,
        privacy_gate: PrivacyGate | None = None,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._sessions = sessions
        self._budget = budget
        self._masker = masker
        self._events = events
        self._clock = clock
        self._sleeper = sleeper
        self._random = random
        self._ids = ids
        self._verify_model = verify_model
        self._test_hook = test_hook
        self._metrics = metrics
        self._summarizer = summarizer
        self._indexer = indexer
        self._research = research
        self._tool_runner = tool_runner
        self._safety_gate = safety_gate
        self._approval_store = approval_store
        self._audit = audit_writer or NullAuditWriter()
        self._task_store = task_store
        self._privacy_gate = privacy_gate
        self._verified = verify_model is None
        self._prompt = PromptAssembler(llm, settings.llm.context)
        self._history: list[Message] = []
        self._session_id: str | None = None
        self._active_cancel: CancellationToken | None = None
        self._pending_tool_call: ToolCall | None = None
        self._pending_verdict: Verdict | None = None
        self._pending_context: RequestContext | None = None
        self._pending_task_id: str | None = None
        self._pending_step_no: int | None = None
        self._agent: AgentRunner | None = None
        if (
            task_store is not None
            and tool_runner is not None
            and safety_gate is not None
        ):
            self._agent = AgentRunner(
                settings=settings,
                llm=llm,
                tasks=task_store,
                tool_runner=tool_runner,
                safety_gate=safety_gate,
                registry=tool_runner.registry,
                budget=budget,
                prompt=self._prompt,
            )

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def history(self) -> tuple[Message, ...]:
        return tuple(self._history)

    def start(self) -> str:
        if self._session_id is not None:
            return self._session_id
        session_id = self._ids.new("ses")
        now = self._clock.now()
        self._sessions.start_session(session_id, now)
        self._events.emit(
            "session.start",
            {"resumed_from": None},
            identity=EventIdentity(session_id=session_id),
        )
        self._session_id = session_id
        return session_id

    def clear(self) -> None:
        self._history.clear()

    def budget_status(self) -> BudgetStatus:
        return self._budget.status(self._clock.now())

    @property
    def approval_store(self) -> ApprovalStore | None:
        return self._approval_store

    @property
    def pending_context(self) -> RequestContext | None:
        return self._pending_context

    @property
    def task_store(self) -> TaskStore | None:
        return self._task_store

    def mark_step_resolved(
        self,
        task_id: str,
        step_no: int,
        *,
        succeeded: bool,
        result_summary: str,
        changed_paths: tuple[str, ...] = (),
    ) -> None:
        if self._task_store is None:
            raise RuntimeError("TaskStore가 구성되지 않았습니다.")
        now = self._clock.now()
        self._task_store.mark_step_resolved(
            task_id,
            step_no,
            state="succeeded" if succeeded else "failed",
            result_summary=result_summary,
            changed_paths=changed_paths,
            now=now,
        )

    def _agent_turn_outcome(self, result: AgentResult, *, ctx: RequestContext) -> TurnOutcome:
        if result.pending_approval is not None:
            self._pending_tool_call = result.pending_tool_call
            self._pending_verdict = result.pending_approval
            self._pending_context = ctx
            self._pending_task_id = result.task_id
            self._pending_step_no = result.pending_step_no
            ctx.events.emit(
                "approval.request",
                {
                    "tool_name": result.pending_approval.tool_name,
                    "args_hash": result.pending_approval.args_hash,
                    "risk": result.pending_approval.risk,
                    "channel": ctx.channel,
                },
            )
        return TurnOutcome(
            ok=result.ok,
            text=result.text,
            request_id=ctx.request_id,
            turn_id=ctx.turn_id,
            input_tokens=result.usage.prompt_tokens,
            output_tokens=result.usage.completion_tokens,
            cost_usd=result.usage.cost_usd,
            pending_approval=result.pending_approval,
            pending_tool_call=result.pending_tool_call,
            task_id=result.task_id,
            steps=result.steps,
        )

    def _start_agent_task(
        self,
        goal: str,
        *,
        ctx: RequestContext,
        initial_tool_call: ToolCall | None = None,
    ) -> TurnOutcome:
        if self._agent is None or self._task_store is None:
            return TurnOutcome(
                ok=False,
                text="에이전트가 구성되지 않았습니다.",
                request_id=ctx.request_id,
                turn_id=ctx.turn_id,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
            )
        task_id = self._ids.new("task")
        now = ctx.clock.now()
        self._task_store.create_task(
            task_id=task_id,
            session_id=ctx.session_id,
            request_id=ctx.request_id,
            goal=goal,
            max_steps=self._settings.agent.max_steps,
            now=now,
        )
        ctx = replace(ctx, task_id=task_id)
        agent_result = self._agent.run(
            goal=goal,
            ctx=ctx,
            task_id=task_id,
            initial_response_tool_call=initial_tool_call,
        )
        return self._agent_turn_outcome(agent_result, ctx=ctx)

    def continue_task(
        self,
        task_id: str,
        *,
        channel: Channel = "text",
    ) -> TurnOutcome:
        if self._agent is None or self._task_store is None:
            return TurnOutcome(
                ok=False,
                text="에이전트가 구성되지 않았습니다.",
                request_id=self._ids.new("req"),
                turn_id=self._ids.new("turn"),
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
            )
        task = self._task_store.get_task(task_id)
        if task is None:
            return TurnOutcome(
                ok=False,
                text="작업을 찾을 수 없습니다.",
                request_id=self._ids.new("req"),
                turn_id=self._ids.new("turn"),
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
            )
        session_id = self.start()
        request_id = self._ids.new("req")
        turn_id = self._ids.new("turn")
        ctx = RequestContext(
            request_id=request_id,
            session_id=session_id,
            turn_id=turn_id,
            task_id=task_id,
            started_at=self._clock.now(),
            clock=self._clock,
            sleeper=self._sleeper,
            random=self._random,
            settings=self._settings,
            events=BoundEventWriter(
                self._events,
                EventIdentity(request_id=request_id, session_id=session_id, turn_id=turn_id),
            ),
            audit=self._audit,
            cancel=CancellationToken(),
            interactive=True,
            channel=channel,
        )
        steps = self._task_store.list_steps(task_id)
        running = [step for step in steps if step.state == "running"]
        if running:
            step = running[0]
            return TurnOutcome(
                ok=False,
                text=(
                    f"실행 중인 단계({step.step_no}.{step.tool_name})가 있습니다. "
                    "완료/실패 판정 후 계속하세요."
                ),
                request_id=ctx.request_id,
                turn_id=ctx.turn_id,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
                task_id=task_id,
                steps=tuple(steps),
            )
        succeeded_nos = [step.step_no for step in steps if step.state == "succeeded"]
        next_step = max(succeeded_nos, default=0) + 1
        agent_result = self._agent.run(
            goal=task.goal,
            ctx=ctx,
            task_id=task_id,
            resume_step_no=next_step,
        )
        return self._agent_turn_outcome(agent_result, ctx=ctx)

    def cancel_current(self) -> None:
        if self._active_cancel is not None:
            self._active_cancel.cancel()
        self.discard_pending_approval(cause="interrupt")

    def discard_pending_approval(self, *, cause: str = "new_input") -> None:
        if self._pending_verdict is None:
            return
        if self._pending_context is not None:
            self._pending_context.events.emit(
                "approval.cancel",
                {
                    "tool_name": self._pending_verdict.tool_name,
                    "args_hash": self._pending_verdict.args_hash,
                    "cause": cause,
                },
            )
        if (
            cause == "user_deny"
            and self._pending_task_id is not None
            and self._pending_step_no is not None
            and self._task_store is not None
        ):
            now = self._clock.now()
            self._task_store.mark_step_finished(
                self._pending_task_id,
                self._pending_step_no,
                state="cancelled",
                result_summary="사용자가 승인을 거부했습니다.",
                changed_paths=(),
                now=now,
            )
            self._task_store.update_task_state(self._pending_task_id, "cancelled", now=now)
        self._pending_tool_call = None
        self._pending_verdict = None
        self._pending_context = None
        self._pending_task_id = None
        self._pending_step_no = None

    def has_pending_approval(self) -> bool:
        return self._pending_verdict is not None

    def execute_tool_call(
        self,
        call: ToolCall,
        *,
        ctx: RequestContext,
        ticket: ApprovalTicket | None = None,
    ) -> TurnOutcome:
        if self._tool_runner is None:
            return TurnOutcome(
                ok=False,
                text="도구 실행기가 구성되지 않았습니다.",
                request_id=ctx.request_id,
                turn_id=ctx.turn_id,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
            )
        try:
            result = self._tool_runner.execute(call, ctx=ctx, ticket=ticket)
            ctx.events.emit(
                "tool.result",
                {
                    "tool_name": call.name,
                    "args_hash": None,
                    "ok": result.ok,
                    "duration_ms": result.duration_ms,
                    "changed_paths": list(result.changed_paths),
                    "truncated": result.truncated,
                    "error": result.error,
                },
            )
            return TurnOutcome(
                ok=result.ok,
                text=result.output,
                request_id=ctx.request_id,
                turn_id=ctx.turn_id,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
            )
        except ApprovalRequired as error:
            verdict = error.verdict
            if not isinstance(verdict, Verdict):
                raise
            self._pending_tool_call = call
            self._pending_verdict = verdict
            self._pending_context = ctx
            self._pending_task_id = ctx.task_id
            self._pending_step_no = None
            ctx.events.emit(
                "approval.request",
                {
                    "tool_name": verdict.tool_name,
                    "args_hash": verdict.args_hash,
                    "risk": verdict.risk,
                    "channel": ctx.channel,
                },
            )
            return TurnOutcome(
                ok=False,
                text=verdict.display,
                request_id=ctx.request_id,
                turn_id=ctx.turn_id,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
                pending_approval=verdict,
                pending_tool_call=call,
            )
        except JarvisError as error:
            return TurnOutcome(
                ok=False,
                text=error.user_message,
                request_id=ctx.request_id,
                turn_id=ctx.turn_id,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
            )

    def resume_after_approval(
        self,
        ticket: ApprovalTicket,
        *,
        channel: Channel = "text",
    ) -> TurnOutcome:
        if self._pending_tool_call is None or self._pending_context is None:
            return TurnOutcome(
                ok=False,
                text="대기 중인 승인 요청이 없습니다.",
                request_id=self._ids.new("req"),
                turn_id=self._ids.new("turn"),
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
            )
        call = self._pending_tool_call
        ctx = replace(self._pending_context, channel=channel)
        task_id = self._pending_task_id
        step_no = self._pending_step_no
        goal = ""
        if task_id is not None and self._task_store is not None:
            task = self._task_store.get_task(task_id)
            if task is not None:
                goal = task.goal
        self._pending_tool_call = None
        self._pending_verdict = None
        self._pending_context = None
        self._pending_task_id = None
        self._pending_step_no = None
        ctx.events.emit(
            "approval.grant",
            {
                "ticket_id": ticket.id,
                "tool_name": ticket.tool_name,
                "args_hash": ticket.args_hash,
                "method": ticket.granted_by,
                "expires_at": ticket.expires_at.isoformat(timespec="milliseconds"),
            },
        )
        if task_id is not None and self._agent is not None and step_no is not None:
            agent_result = self._agent.run(
                goal=goal,
                ctx=ctx,
                task_id=task_id,
                initial_response_tool_call=call,
                resume_step_no=step_no,
                resume_ticket=ticket,
            )
            return self._agent_turn_outcome(agent_result, ctx=ctx)
        return self.execute_tool_call(call, ctx=ctx, ticket=ticket)

    def memory_command_context(self, *, turn_id: str | None = None) -> MemoryCommandContext | None:
        if self._session_id is None:
            return None
        export_dir = self._sessions._export_dir
        return MemoryCommandContext(
            store=self._sessions,
            ids=self._ids,
            clock=self._clock,
            session_id=self._session_id,
            key_aliases=self._sessions._key_aliases,
            export_dir=Path(export_dir) if export_dir is not None else None,
            turn_id=turn_id,
            events=self._events,
            privacy_gate=self._privacy_gate,
        )

    def handle_index(self) -> str:
        if self._indexer is None:
            return "문서 인덱서가 구성되지 않았습니다."
        report = run_index(self._indexer)
        return (
            f"인덱싱 완료: 신규 {report.indexed}, 갱신 {report.updated}, "
            f"삭제 {report.removed}, 건너뜀 {report.skipped}"
            + (f", 오류 {len(report.errors)}" if report.errors else "")
        )

    def _safe_llm_text(self, text: str) -> str:
        if self._privacy_gate is not None:
            return self._privacy_gate.for_llm_local(text)
        return self._masker.for_log(text)

    def _memory_budget_tokens(self) -> int:
        context = self._settings.llm.context
        available = context.max_input_tokens - context.reserve_output_tokens
        return max(0, int(available * context.memory_share))

    def _prepare_memory_blocks(
        self,
        text: str,
        *,
        bound_events: BoundEventWriter,
    ) -> tuple[str | None, str | None, tuple[str, ...]]:
        retrieval = self._settings.memory.retrieval
        result = self._sessions.search(
            MemoryQuery(
                text=text,
                top_k=retrieval.top_k,
                include_candidates=retrieval.include_candidates,
                now=self._clock.now(),
            )
        )
        bound_events.emit(
            "memory.search",
            {
                "query_len": len(text),
                "match_count": len(result.matches),
                "candidate_count": len(result.candidates),
                "record_ids": [item.record.id for item in result.matches],
            },
        )
        token_budget = self._memory_budget_tokens()
        _, _, confirmed_block, candidate_block = trim_memory_for_budget(
            result.matches,
            result.candidates,
            token_budget=token_budget,
            count_tokens=lambda block: self._llm.count_tokens((Message("system", block),)),
        )
        record_ids = tuple(
            item.record.id for item in (*result.matches, *result.candidates)
        )
        return confirmed_block, candidate_block, record_ids

    def _try_research_turn(
        self,
        text: str,
        *,
        context: RequestContext,
        bound_events: BoundEventWriter,
        session_id: str,
        turn_id: str,
        request_id: str,
        channel: Channel,
        turn_started_ms: int,
        cancel: CancellationToken,
    ) -> TurnOutcome | None:
        if self._research is None:
            return None
        command_query = parse_search_command(text)
        query: str | None
        if command_query is not None:
            if not command_query:
                return TurnOutcome(
                    ok=False,
                    text="검색어를 입력하세요. 예: /search Jarvis RAG",
                    request_id=request_id,
                    turn_id=turn_id,
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=Decimal("0"),
                )
            query = command_query
        elif should_auto_search(text):
            query = text.strip()
        else:
            return None

        bundle = self._research.run(query, ctx=context)
        bound_events.emit(
            "tool.result",
            {
                "tool_name": "research",
                "ok": bundle.status_hint != "검색 실패",
                "web_ok": None if bundle.web is None else bundle.web.ok,
                "doc_ok": None if bundle.docs is None else bundle.docs.ok,
                "status_hint": bundle.status_hint,
            },
        )
        if bundle.status_hint == "검색 실패":
            message = bundle.web.error if bundle.web is not None else "검색에 실패했습니다."
            return TurnOutcome(
                ok=False,
                text=message or "검색에 실패했습니다.",
                request_id=request_id,
                turn_id=turn_id,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
            )
        if bundle.status_hint == "결과 없음":
            return TurnOutcome(
                ok=True,
                text="검색 결과가 없습니다. /index로 문서를 동기화했는지 확인하세요.",
                request_id=request_id,
                turn_id=turn_id,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
            )

        estimated_cost = estimate_llm_cost(
            self._settings.llm,
            prompt_tokens=self._settings.llm.context.max_input_tokens,
            max_output_tokens=self._settings.llm.max_output_tokens,
        )
        self._budget.check("llm", estimated_cost, ctx=context)
        research_context = build_research_context(bundle)
        tools_prompt = load_tools_prompt()
        plan = self._prompt.build(
            current_user_text=f"{text}\n\n{research_context}",
            history=self._history,
            cancel=cancel,
            confirmed_memory=None,
            candidate_memory=None,
            extra_system=(tools_prompt,),
        )
        response = self._llm.complete(
            messages=plan.messages,
            timeout_s=self._settings.llm.timeout_s,
            ctx=context,
            temperature=self._settings.llm.temperature,
            max_output_tokens=self._settings.llm.max_output_tokens,
        )
        if response.text is None:
            raise LLMBadResponse("LLM 응답 본문이 없습니다.")
        self._budget.record_llm(response.usage, ctx=context)
        if self._metrics is not None:
            metric_time = self._clock.now()
            self._metrics.record_ms(
                "llm.latency",
                response.usage.latency_ms,
                at=metric_time,
                labels={"model": response.model, "attempt": 1},
            )
            self._metrics.record_num(
                "llm.cost",
                float(response.usage.cost_usd),
                at=metric_time,
                labels={"model": response.model},
            )
            self._metrics.record_ms(
                "turn.latency",
                max(0, self._clock.monotonic_ms() - turn_started_ms),
                at=metric_time,
                labels={"channel": channel, "used_tools": True},
            )
        answer_text = enforce_research_status(response.text, bundle)
        masked_response = self._masker.for_log(answer_text)
        self._sessions.append_raw(
            RawRecord(
                ts=self._clock.now(),
                session_id=session_id,
                turn_id=turn_id,
                role="assistant",
                content=masked_response,
                channel=channel,
                request_id=request_id,
                meta={"used_tools": True, "research": True},
            )
        )
        self._history.extend(
            (Message("user", self._safe_llm_text(text)), Message("assistant", answer_text))
        )
        return TurnOutcome(
            ok=True,
            text=answer_text,
            request_id=request_id,
            turn_id=turn_id,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            cost_usd=response.usage.cost_usd,
        )

    def handle_turn(self, text: str, *, channel: Channel = "text") -> TurnOutcome:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("사용자 입력은 비어 있을 수 없습니다")
        if channel not in {"text", "voice"}:
            raise ValueError("channel must be text or voice")
        session_id = self.start()
        turn_started_ms = self._clock.monotonic_ms()
        request_id = self._ids.new("req")
        turn_id = self._ids.new("turn")
        now = self._clock.now()
        identity = EventIdentity(
            request_id=request_id,
            session_id=session_id,
            turn_id=turn_id,
        )
        bound_events = BoundEventWriter(
            self._events,
            identity,
            after_emit=None if self._test_hook is None else self._test_hook.after,
        )
        cancel = CancellationToken()
        context = RequestContext(
            request_id=request_id,
            session_id=session_id,
            turn_id=turn_id,
            task_id=None,
            started_at=now,
            clock=self._clock,
            sleeper=self._sleeper,
            random=self._random,
            settings=self._settings,
            events=bound_events,
            audit=self._audit,
            cancel=cancel,
            interactive=True,
            channel=channel,
        )
        masked_input = self._masker.for_log(text)
        self._sessions.append_raw(
            RawRecord(
                ts=now,
                session_id=session_id,
                turn_id=turn_id,
                role="user",
                content=masked_input,
                channel=channel,
                request_id=request_id,
            )
        )
        bound_events.emit(
            "user.input",
            {"text_len": len(text), "channel": channel, "text": text},
        )

        self._active_cancel = cancel
        try:
            if self._pending_verdict is not None:
                self.discard_pending_approval(cause="new_input")

            if self._safety_gate is not None:
                forbidden = self._safety_gate.check_forbidden_user_text(text)
                if forbidden is not None:
                    bound_events.emit(
                        "policy.deny",
                        {
                            "tool_name": None,
                            "rule": forbidden.id,
                            "reason": forbidden.reason,
                        },
                    )
                    return TurnOutcome(
                        ok=False,
                        text=forbidden.reason,
                        request_id=request_id,
                        turn_id=turn_id,
                        input_tokens=0,
                        output_tokens=0,
                        cost_usd=Decimal("0"),
                    )

            tool_call = parse_tool_command(text)
            if tool_call is not None and self._tool_runner is not None:
                outcome = self.execute_tool_call(tool_call, ctx=context)
                if outcome.pending_approval is None:
                    self._sessions.append_raw(
                        RawRecord(
                            ts=self._clock.now(),
                            session_id=session_id,
                            turn_id=turn_id,
                            role="assistant",
                            content=self._masker.for_log(outcome.text),
                            channel=channel,
                            request_id=request_id,
                            meta={"used_tools": True, "tool_name": tool_call.name},
                        )
                    )
                return outcome

            research_outcome = None
            if not should_run_agent_goal(text):
                research_outcome = self._try_research_turn(
                    text,
                    context=context,
                    bound_events=bound_events,
                    session_id=session_id,
                    turn_id=turn_id,
                    request_id=request_id,
                    channel=channel,
                    turn_started_ms=turn_started_ms,
                    cancel=cancel,
                )
            if research_outcome is not None:
                return research_outcome
            if should_run_agent_goal(text) and self._agent is not None:
                agent_outcome = self._start_agent_task(text, ctx=context)
                if agent_outcome.pending_approval is None:
                    self._sessions.append_raw(
                        RawRecord(
                            ts=self._clock.now(),
                            session_id=session_id,
                            turn_id=turn_id,
                            role="assistant",
                            content=self._masker.for_log(agent_outcome.text),
                            channel=channel,
                            request_id=request_id,
                            meta={
                                "used_tools": True,
                                "agent": True,
                                "task_id": agent_outcome.task_id,
                            },
                        )
                    )
                    self._history.extend(
                        (
                            Message("user", self._safe_llm_text(text)),
                            Message("assistant", agent_outcome.text),
                        )
                    )
                return agent_outcome
            if not self._verified and self._verify_model is not None:
                self._verify_model()
                self._verified = True
            estimated_cost = estimate_llm_cost(
                self._settings.llm,
                prompt_tokens=self._settings.llm.context.max_input_tokens,
                max_output_tokens=self._settings.llm.max_output_tokens,
            )
            self._budget.check("llm", estimated_cost, ctx=context)
            confirmed_block, candidate_block, memory_record_ids = self._prepare_memory_blocks(
                text,
                bound_events=bound_events,
            )
            context = replace(context, memory_record_ids=memory_record_ids)
            safe_user_text = self._safe_llm_text(text)
            plan = self._prompt.build(
                current_user_text=safe_user_text,
                history=self._history,
                cancel=cancel,
                confirmed_memory=confirmed_block,
                candidate_memory=candidate_block,
            )
            response = self._llm.complete(
                messages=plan.messages,
                timeout_s=self._settings.llm.timeout_s,
                ctx=context,
                temperature=self._settings.llm.temperature,
                max_output_tokens=self._settings.llm.max_output_tokens,
            )
            if response.tool_calls and self._tool_runner is not None and self._agent is not None:
                agent_outcome = self._start_agent_task(
                    text,
                    ctx=context,
                    initial_tool_call=response.tool_calls[0],
                )
                if agent_outcome.pending_approval is None:
                    self._sessions.append_raw(
                        RawRecord(
                            ts=self._clock.now(),
                            session_id=session_id,
                            turn_id=turn_id,
                            role="assistant",
                            content=self._masker.for_log(agent_outcome.text),
                            channel=channel,
                            request_id=request_id,
                            meta={
                                "used_tools": True,
                                "agent": True,
                                "task_id": agent_outcome.task_id,
                            },
                        )
                    )
                    self._history.extend(
                        (
                            Message("user", self._safe_llm_text(text)),
                            Message("assistant", agent_outcome.text),
                        )
                    )
                return agent_outcome
            if response.tool_calls and self._tool_runner is not None:
                tool_outcome = self.execute_tool_call(response.tool_calls[0], ctx=context)
                if tool_outcome.pending_approval is not None:
                    return tool_outcome
                assistant_text = tool_outcome.text
                used_tools = True
            elif response.text is None:
                raise LLMBadResponse("LLM 응답 본문이 없습니다.")
            else:
                assistant_text = response.text
                used_tools = False
            self._budget.record_llm(response.usage, ctx=context)
            if self._metrics is not None:
                metric_time = self._clock.now()
                self._metrics.record_ms(
                    "llm.latency",
                    response.usage.latency_ms,
                    at=metric_time,
                    labels={"model": response.model, "attempt": 1},
                )
                self._metrics.record_num(
                    "llm.cost",
                    float(response.usage.cost_usd),
                    at=metric_time,
                    labels={"model": response.model},
                )
            masked_response = self._masker.for_log(assistant_text)
            self._sessions.append_raw(
                RawRecord(
                    ts=self._clock.now(),
                    session_id=session_id,
                    turn_id=turn_id,
                    role="assistant",
                    content=masked_response,
                    channel=channel,
                    request_id=request_id,
                    meta={
                        "model": response.model,
                        "finish_reason": response.finish_reason,
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "cost_usd": format(response.usage.cost_usd, "f"),
                        "used_tools": used_tools,
                    },
                )
            )
            if self._test_hook is not None:
                self._test_hook.after("memory.write")
            session = self._sessions.record_turn(session_id, response.usage)
            self._history.extend(
                (
                    Message("user", self._safe_llm_text(text)),
                    Message("assistant", assistant_text),
                )
            )
            if session.turn_count % self._settings.memory.checkpoint_every_turns == 0:
                checkpoint_seq = session.turn_count // self._settings.memory.checkpoint_every_turns
                self._sessions.checkpoint(
                    session_id,
                    seq=checkpoint_seq,
                    created_at=self._clock.now(),
                    last_turn_id=turn_id,
                    turn_count=session.turn_count,
                )
                bound_events.emit(
                    "session.checkpoint",
                    {
                        "turn_count": session.turn_count,
                        "last_turn_id": turn_id,
                        "usage_total": {
                            "cost_usd": format(session.cost_usd, "f"),
                            "tokens_in": session.tokens_in,
                            "tokens_out": session.tokens_out,
                        },
                    },
                )
            if self._metrics is not None:
                self._metrics.record_ms(
                    "turn.latency",
                    max(0, self._clock.monotonic_ms() - turn_started_ms),
                    at=self._clock.now(),
                    labels={"channel": channel, "used_tools": used_tools},
                )
            return TurnOutcome(
                ok=True,
                text=assistant_text,
                request_id=request_id,
                turn_id=turn_id,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                cost_usd=response.usage.cost_usd,
            )
        except InterruptedError:
            raise
        except Exception as error:
            user_message = (
                error.user_message
                if isinstance(error, JarvisError)
                else "응답을 처리하는 중 예상하지 못한 오류가 발생했습니다."
            )
            detail = error.detail if isinstance(error, JarvisError) else {}
            self._sessions.append_raw(
                RawRecord(
                    ts=self._clock.now(),
                    session_id=session_id,
                    turn_id=turn_id,
                    role="system_note",
                    content=self._masker.for_log(user_message),
                    channel=channel,
                    request_id=request_id,
                    meta={"status": "error", "error_type": type(error).__name__},
                )
            )
            bound_events.emit(
                "error",
                {
                    "error_type": type(error).__name__,
                    "user_message": user_message,
                    "detail": detail,
                    "handled": True,
                },
            )
            return TurnOutcome(
                ok=False,
                text=user_message,
                request_id=request_id,
                turn_id=turn_id,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
            )
        finally:
            self._active_cancel = None

    def end(self, *, reason: EndReason = "bye") -> None:
        if self._session_id is None:
            return
        session_id = self._session_id
        summary_record_id: str | None = None
        candidate_count = 0

        if self._settings.memory.summarize_on_exit and self._summarizer is not None:
            summary_turn_id = self._ids.new("turn")
            summary_ctx = RequestContext(
                request_id=self._ids.new("req"),
                session_id=session_id,
                turn_id=summary_turn_id,
                task_id=None,
                started_at=self._clock.now(),
                clock=self._clock,
                sleeper=self._sleeper,
                random=self._random,
                settings=self._settings,
                events=BoundEventWriter(
                    self._events,
                    EventIdentity(session_id=session_id, turn_id=summary_turn_id),
                ),
                audit=self._audit,
                cancel=CancellationToken(),
                interactive=False,
                channel="text",
            )
            summary = self._summarizer.summarize_session(
                session_id,
                ctx=summary_ctx,
                timeout_s=self._settings.llm.timeout_s,
                temperature=self._settings.llm.temperature,
                max_output_tokens=self._settings.llm.max_output_tokens,
            )
            if summary is not None:
                summary_record_id = summary.summary_record_id
                candidate_count = len(summary.fact_candidates)

        ended = self._sessions.end_session(
            session_id,
            ended_at=self._clock.now(),
            reason=reason,
        )
        self._events.emit(
            "session.end",
            {
                "turn_count": ended.turn_count,
                "summary_record_id": summary_record_id,
                "candidate_count": candidate_count,
            },
            identity=EventIdentity(session_id=session_id),
        )
        self._session_id = None
        self._history.clear()

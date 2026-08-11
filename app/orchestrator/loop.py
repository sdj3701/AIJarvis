"""Phase 1 turn orchestration with write-ahead user input durability."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from app.budget import BudgetGuard, BudgetStatus, estimate_llm_cost
from app.config.models import Settings
from app.core.clock import Clock, RandomSource, Sleeper
from app.core.context import CancellationToken, RequestContext
from app.core.errors import JarvisError, LLMBadResponse
from app.core.ids import PrefixedIdFactory
from app.core.test_hooks import CrashTestHook
from app.llm.base import LLMClient, Message
from app.memory.store import Channel, EndReason, RawRecord, SQLiteSessionStore
from app.orchestrator.prompt import PromptAssembler
from app.telemetry.events import EventIdentity
from app.telemetry.masking import LogMasker
from app.telemetry.metrics import SQLiteMetrics


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
        self._verified = verify_model is None
        self._prompt = PromptAssembler(llm, settings.llm.context)
        self._history: list[Message] = []
        self._session_id: str | None = None
        self._active_cancel: CancellationToken | None = None

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

    def cancel_current(self) -> None:
        if self._active_cancel is not None:
            self._active_cancel.cancel()

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
            audit=NullAuditWriter(),
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
            if not self._verified and self._verify_model is not None:
                self._verify_model()
                self._verified = True
            estimated_cost = estimate_llm_cost(
                self._settings.llm,
                prompt_tokens=self._settings.llm.context.max_input_tokens,
                max_output_tokens=self._settings.llm.max_output_tokens,
            )
            self._budget.check("llm", estimated_cost, ctx=context)
            plan = self._prompt.build(
                current_user_text=text,
                history=self._history,
                cancel=cancel,
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
            masked_response = self._masker.for_log(response.text)
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
                    },
                )
            )
            if self._test_hook is not None:
                self._test_hook.after("memory.write")
            session = self._sessions.record_turn(session_id, response.usage)
            self._history.extend((Message("user", text), Message("assistant", response.text)))
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
                    labels={"channel": channel, "used_tools": False},
                )
            return TurnOutcome(
                ok=True,
                text=response.text,
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
        ended = self._sessions.end_session(
            session_id,
            ended_at=self._clock.now(),
            reason=reason,
        )
        self._events.emit(
            "session.end",
            {
                "turn_count": ended.turn_count,
                "summary_record_id": None,
                "candidate_count": 0,
            },
            identity=EventIdentity(session_id=session_id),
        )
        self._session_id = None
        self._history.clear()

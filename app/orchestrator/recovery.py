"""Session and agent-task recovery after an unclean shutdown.

Filesystem ``*.tmp`` / JSONL tail recovery lives in ``app.core.recovery``
and is re-exported here so existing imports keep working.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.config.models import Settings
from app.core.clock import Clock, RandomSource, Sleeper
from app.core.context import CancellationToken, RequestContext
from app.core.ids import PrefixedIdFactory
from app.core.recovery import RecoveryAction, RecoveryReport, recover_jsonl_tail, recover_startup
from app.memory.store import EndReason, SQLiteSessionStore
from app.memory.summarizer import SessionSummarizer
from app.orchestrator.tasks import TaskStore

_SIDE_EFFECT_TOOLS = frozenset({"create_file", "open_app", "open_folder", "open_url", "run_skill"})

__all__ = [
    "RecoveryAction",
    "RecoveryReport",
    "SessionRecoveryAction",
    "SessionRecoveryReport",
    "TaskRecoveryAction",
    "TaskRecoveryReport",
    "recover_jsonl_tail",
    "recover_sessions",
    "recover_startup",
    "recover_tasks",
]


class EventSink(Protocol):
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


class AuditWriter(Protocol):
    def write(self, record: Mapping[str, Any]) -> None: ...


class NullAuditWriter:
    def write(self, record: Mapping[str, Any]) -> None:
        del record


@dataclass(frozen=True, slots=True)
class TaskRecoveryAction:
    task_id: str
    step_no: int | None
    action: Literal[
        "running_needs_judgment",
        "pending_needs_fresh_approval",
        "left_running",
        "none",
    ]
    changed_paths: tuple[str, ...] = ()
    tool_name: str | None = None


@dataclass(frozen=True, slots=True)
class TaskRecoveryReport:
    running_tasks: int
    running_steps: int
    pending_steps: int
    actions: tuple[TaskRecoveryAction, ...]


@dataclass(frozen=True, slots=True)
class SessionRecoveryAction:
    session_id: str
    action: Literal["left_open", "discarded", "recovered", "summarized"]
    summary_record_id: str | None = None
    candidate_count: int = 0


@dataclass(frozen=True, slots=True)
class SessionRecoveryReport:
    integrity_problems: tuple[str, ...]
    unfinished_count: int
    actions: tuple[SessionRecoveryAction, ...]


def recover_sessions(
    store: SQLiteSessionStore,
    *,
    policy: Literal["prompt", "auto", "discard"],
    events: EventSink,
    clock: Clock,
    summarizer: SessionSummarizer | None = None,
    settings: Settings | None = None,
    ids: PrefixedIdFactory | None = None,
    sleeper: Sleeper | None = None,
    random: RandomSource | None = None,
) -> SessionRecoveryReport:
    """Recover unfinished sessions after DB integrity check."""
    problems = tuple(store.integrity_check())
    unfinished = store.unfinished_sessions()
    events.emit(
        "recovery.start",
        {
            "unfinished_sessions": len(unfinished),
            "tmp_files": 0,
            "running_steps": 0,
            "integrity_problems": len(problems),
        },
    )

    actions: list[SessionRecoveryAction] = []
    for session in unfinished:
        if policy == "prompt":
            actions.append(SessionRecoveryAction(session.session_id, "left_open"))
            events.emit(
                "recovery.result",
                {
                    "action": "left_open",
                    "session_id": session.session_id,
                    "quarantined": None,
                    "restored_turns": session.turn_count,
                },
            )
            continue

        reason: EndReason = "discarded" if policy == "discard" else "crash_recovered"
        summary_record_id: str | None = None
        candidate_count = 0
        if (
            policy == "auto"
            and summarizer is not None
            and settings is not None
            and ids is not None
            and sleeper is not None
            and random is not None
        ):
            turn_id = ids.new("turn")
            ctx = RequestContext(
                request_id=ids.new("req"),
                session_id=session.session_id,
                turn_id=turn_id,
                task_id=None,
                started_at=clock.now(),
                clock=clock,
                sleeper=sleeper,
                random=random,
                settings=settings,
                events=events,
                audit=NullAuditWriter(),
                cancel=CancellationToken(),
                interactive=False,
                channel="text",
            )
            summary = summarizer.summarize_session(session.session_id, ctx=ctx)
            if summary is not None:
                summary_record_id = summary.summary_record_id
                candidate_count = len(summary.fact_candidates)

        store.end_session(session.session_id, ended_at=clock.now(), reason=reason)
        action_name: Literal["discarded", "recovered", "summarized"] = (
            "discarded"
            if policy == "discard"
            else "summarized"
            if summary_record_id
            else "recovered"
        )
        actions.append(
            SessionRecoveryAction(
                session.session_id,
                action_name,
                summary_record_id=summary_record_id,
                candidate_count=candidate_count,
            )
        )
        events.emit(
            "recovery.result",
            {
                "action": action_name,
                "session_id": session.session_id,
                "quarantined": None,
                "restored_turns": session.turn_count,
                "summary_record_id": summary_record_id,
                "candidate_count": candidate_count,
            },
        )

    if not actions:
        events.emit(
            "recovery.result",
            {
                "action": "none",
                "session_id": None,
                "quarantined": None,
                "restored_turns": 0,
            },
        )

    return SessionRecoveryReport(
        integrity_problems=problems,
        unfinished_count=len(unfinished),
        actions=tuple(actions),
    )


def recover_tasks(task_store: TaskStore, events: EventSink) -> TaskRecoveryReport:
    """Surface running agent tasks/steps; never auto re-execute side effects."""
    running_tasks = task_store.list_running_tasks()
    running_steps = task_store.list_running_steps()
    pending_steps = task_store.list_pending_steps()
    actions: list[TaskRecoveryAction] = []

    for step in pending_steps:
        action = TaskRecoveryAction(
            task_id=step.task_id,
            step_no=step.step_no,
            action="pending_needs_fresh_approval",
            tool_name=step.tool_name,
        )
        actions.append(action)
        events.emit(
            "recovery.result",
            {
                "action": "pending_needs_fresh_approval",
                "task_id": step.task_id,
                "step_no": step.step_no,
                "tool_name": step.tool_name,
                "session_id": None,
                "quarantined": None,
                "restored_turns": 0,
            },
        )

    for step in running_steps:
        if step.tool_name in _SIDE_EFFECT_TOOLS:
            action = TaskRecoveryAction(
                task_id=step.task_id,
                step_no=step.step_no,
                action="running_needs_judgment",
                changed_paths=step.changed_paths,
                tool_name=step.tool_name,
            )
            actions.append(action)
            events.emit(
                "recovery.result",
                {
                    "action": "running_needs_judgment",
                    "task_id": step.task_id,
                    "step_no": step.step_no,
                    "tool_name": step.tool_name,
                    "changed_paths": list(step.changed_paths),
                    "session_id": None,
                    "quarantined": None,
                    "restored_turns": 0,
                },
            )
        else:
            actions.append(
                TaskRecoveryAction(
                    task_id=step.task_id,
                    step_no=step.step_no,
                    action="left_running",
                    tool_name=step.tool_name,
                )
            )
            events.emit(
                "recovery.result",
                {
                    "action": "left_running",
                    "task_id": step.task_id,
                    "step_no": step.step_no,
                    "tool_name": step.tool_name,
                    "session_id": None,
                    "quarantined": None,
                    "restored_turns": 0,
                },
            )

    for task in running_tasks:
        if not any(action.task_id == task.task_id for action in actions):
            actions.append(
                TaskRecoveryAction(task_id=task.task_id, step_no=None, action="left_running")
            )

    if not actions:
        events.emit(
            "recovery.result",
            {
                "action": "none",
                "task_id": None,
                "session_id": None,
                "quarantined": None,
                "restored_turns": 0,
            },
        )

    return TaskRecoveryReport(
        running_tasks=len(running_tasks),
        running_steps=len(running_steps),
        pending_steps=len(pending_steps),
        actions=tuple(actions),
    )

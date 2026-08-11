"""Extend startup recovery for incomplete agent tasks and steps."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from app.config.models import Settings
from app.core.atomic import write_atomic
from app.core.clock import Clock, RandomSource, Sleeper
from app.core.context import CancellationToken, RequestContext
from app.core.errors import RecoveryError
from app.core.ids import PrefixedIdFactory
from app.memory.store import EndReason, SQLiteSessionStore
from app.memory.summarizer import SessionSummarizer
from app.orchestrator.tasks import TaskStore

_SIDE_EFFECT_TOOLS = frozenset({"create_file", "open_app", "open_folder", "open_url", "run_skill"})


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
class RecoveryAction:
    action: str
    source: Path | None
    quarantined: Path | None
    restored_turns: int


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    tmp_files: int
    broken_tails: int
    actions: tuple[RecoveryAction, ...]


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


def _unique_target(directory: Path, name: str) -> Path:
    candidate = directory / name
    sequence = 1
    while candidate.exists():
        candidate = directory / f"{name}.{sequence}"
        sequence += 1
    return candidate


def _quarantine_tmp(data_root: Path, source: Path, quarantine: Path) -> Path:
    relative = source.relative_to(data_root)
    target = _unique_target(quarantine, "__".join(relative.parts))
    os.replace(source, target)
    return target


def _parse_json_line(line: bytes) -> dict[str, Any]:
    decoded = line.decode("utf-8")
    parsed = json.loads(decoded)
    if not isinstance(parsed, dict):
        raise ValueError("JSONL record must be an object")
    return parsed


def recover_jsonl_tail(path: Path, quarantine: Path) -> RecoveryAction | None:
    """Move only a malformed final JSONL line aside and keep all valid lines."""
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    if not lines:
        return None

    for index, line in enumerate(lines):
        try:
            _parse_json_line(line)
        except (UnicodeError, json.JSONDecodeError, ValueError) as error:
            if index != len(lines) - 1:
                raise RecoveryError(
                    "JSONL 중간 레코드가 손상되었습니다.",
                    {"file": path.name, "line": index + 1},
                ) from error
            tail_target = _unique_target(quarantine, f"{path.stem}.tail")
            write_atomic(tail_target, line)
            write_atomic(path, b"".join(lines[:index]))
            return RecoveryAction("quarantine_broken_tail", path, tail_target, restored_turns=index)
    return None


def recover_startup(data_root: Path, events: EventSink) -> RecoveryReport:
    """Perform Phase 0 filesystem recovery and emit a record for every outcome."""
    root = Path(data_root).resolve(strict=False)
    quarantine = root / "state" / "quarantine"
    raw_dir = root / "memory" / "raw"
    quarantine.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    try:
        temporary_files = sorted(
            path
            for path in root.rglob("*.tmp")
            if path.is_file() and not path.is_relative_to(quarantine)
        )
        events.emit(
            "recovery.start",
            {"unfinished_sessions": 0, "tmp_files": len(temporary_files), "running_steps": 0},
        )

        actions: list[RecoveryAction] = []
        for temporary in temporary_files:
            target = _quarantine_tmp(root, temporary, quarantine)
            action = RecoveryAction("quarantine_tmp", temporary, target, restored_turns=0)
            actions.append(action)
            _emit_result(events, action)

        for raw_path in sorted(raw_dir.glob("*.jsonl")):
            tail_action = recover_jsonl_tail(raw_path, quarantine)
            if tail_action is not None:
                actions.append(tail_action)
                _emit_result(events, tail_action)

        if not actions:
            empty_action = RecoveryAction("none", None, None, restored_turns=0)
            actions.append(empty_action)
            _emit_result(events, empty_action)
    except RecoveryError:
        _emit_failure(events)
        raise
    except OSError as error:
        _emit_failure(events)
        raise RecoveryError(
            "시작 복구 중 파일을 안전하게 처리하지 못했습니다.",
            {"error_type": type(error).__name__},
        ) from error

    return RecoveryReport(
        tmp_files=sum(action.action == "quarantine_tmp" for action in actions),
        broken_tails=sum(action.action == "quarantine_broken_tail" for action in actions),
        actions=tuple(actions),
    )


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


def _emit_result(events: EventSink, action: RecoveryAction) -> None:
    events.emit(
        "recovery.result",
        {
            "action": action.action,
            "session_id": action.source.stem
            if action.source and action.source.suffix == ".jsonl"
            else None,
            "quarantined": str(action.quarantined) if action.quarantined else None,
            "restored_turns": action.restored_turns,
        },
    )


def _emit_failure(events: EventSink) -> None:
    events.emit(
        "recovery.result",
        {
            "action": "failed",
            "session_id": None,
            "quarantined": None,
            "restored_turns": 0,
        },
    )

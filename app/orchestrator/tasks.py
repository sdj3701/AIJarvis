"""Task and step persistence with idempotent side-effect tracking."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from app.core.canonical import args_hash as compute_args_hash
from app.memory.migrations import configure_connection
from app.tools.base import ToolResult

TaskState = Literal["pending", "running", "succeeded", "failed", "cancelled"]
StepState = Literal["pending", "running", "succeeded", "failed", "cancelled"]


@dataclass(frozen=True, slots=True)
class TaskRecord:
    task_id: str
    session_id: str
    request_id: str
    goal: str
    state: TaskState
    created_at: datetime
    updated_at: datetime
    max_steps: int


@dataclass(frozen=True, slots=True)
class StepRecord:
    task_id: str
    step_no: int
    tool_name: str
    args_hash: str
    idempotency_key: str
    state: StepState
    result_summary: str | None
    changed_paths: tuple[str, ...]
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class CachedStepResult:
    ok: bool
    output: str
    changed_paths: tuple[str, ...]
    error: str | None


def idempotency_key(task_id: str, step_no: int, tool_name: str, args_hash: str) -> str:
    payload = f"{task_id}\x00{step_no}\x00{tool_name}\x00{args_hash}".encode()
    return hashlib.sha256(payload).hexdigest()


def args_hash_for_tool(tool_name: str, normalized_args: Mapping[str, Any]) -> str:
    return compute_args_hash(tool_name, dict(normalized_args))


class TaskStore:
    """Persist multi-step agent tasks and steps in SQLite."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = Path(database_path)
        self._lock = RLock()

    def create_task(
        self,
        *,
        task_id: str,
        session_id: str,
        request_id: str,
        goal: str,
        max_steps: int,
        now: datetime,
    ) -> TaskRecord:
        record = TaskRecord(
            task_id=task_id,
            session_id=session_id,
            request_id=request_id,
            goal=goal,
            state="pending",
            created_at=now,
            updated_at=now,
            max_steps=max_steps,
        )
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                  task_id, session_id, request_id, goal, state,
                  created_at, updated_at, max_steps
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.task_id,
                    record.session_id,
                    record.request_id,
                    record.goal,
                    record.state,
                    _iso(record.created_at),
                    _iso(record.updated_at),
                    record.max_steps,
                ),
            )
            connection.commit()
        return record

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return None if row is None else _task_from_row(row)

    def update_task_state(self, task_id: str, state: TaskState, *, now: datetime) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                "UPDATE tasks SET state = ?, updated_at = ? WHERE task_id = ?",
                (state, _iso(now), task_id),
            )
            connection.commit()

    def create_step(
        self,
        *,
        task_id: str,
        step_no: int,
        tool_name: str,
        normalized_args: Mapping[str, Any],
    ) -> StepRecord:
        hashed = args_hash_for_tool(tool_name, normalized_args)
        key = idempotency_key(task_id, step_no, tool_name, hashed)
        record = StepRecord(
            task_id=task_id,
            step_no=step_no,
            tool_name=tool_name,
            args_hash=hashed,
            idempotency_key=key,
            state="pending",
            result_summary=None,
            changed_paths=(),
            started_at=None,
            finished_at=None,
        )
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO task_steps (
                  task_id, step_no, tool_name, args_hash, idempotency_key,
                  state, result_summary, changed_paths, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, '[]', NULL, NULL)
                """,
                (
                    record.task_id,
                    record.step_no,
                    record.tool_name,
                    record.args_hash,
                    record.idempotency_key,
                    record.state,
                ),
            )
            connection.commit()
        return record

    def get_step(self, task_id: str, step_no: int) -> StepRecord | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM task_steps WHERE task_id = ? AND step_no = ?",
                (task_id, step_no),
            ).fetchone()
        return None if row is None else _step_from_row(row)

    def list_steps(self, task_id: str) -> tuple[StepRecord, ...]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM task_steps WHERE task_id = ? ORDER BY step_no",
                (task_id,),
            ).fetchall()
        return tuple(_step_from_row(row) for row in rows)

    def mark_step_running(self, task_id: str, step_no: int, *, now: datetime) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                UPDATE task_steps
                SET state = 'running', started_at = ?
                WHERE task_id = ? AND step_no = ?
                """,
                (_iso(now), task_id, step_no),
            )
            connection.commit()

    def mark_step_finished(
        self,
        task_id: str,
        step_no: int,
        *,
        state: StepState,
        result_summary: str | None,
        changed_paths: Sequence[str],
        now: datetime,
    ) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                UPDATE task_steps
                SET state = ?, result_summary = ?, changed_paths = ?,
                    finished_at = ?
                WHERE task_id = ? AND step_no = ?
                """,
                (
                    state,
                    result_summary,
                    json.dumps(list(changed_paths), ensure_ascii=False),
                    _iso(now),
                    task_id,
                    step_no,
                ),
            )
            connection.commit()

    def get_succeeded_by_idempotency(self, key: str) -> CachedStepResult | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT result_summary, changed_paths
                FROM task_steps
                WHERE idempotency_key = ? AND state = 'succeeded'
                """,
                (key,),
            ).fetchone()
        if row is None:
            return None
        summary = row["result_summary"] or ""
        paths = tuple(json.loads(str(row["changed_paths"])))
        return CachedStepResult(ok=True, output=summary, changed_paths=paths, error=None)

    def list_running_tasks(self) -> tuple[TaskRecord, ...]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE state = 'running' ORDER BY updated_at",
            ).fetchall()
        return tuple(_task_from_row(row) for row in rows)

    def list_running_steps(self) -> tuple[StepRecord, ...]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM task_steps WHERE state = 'running' ORDER BY task_id, step_no",
            ).fetchall()
        return tuple(_step_from_row(row) for row in rows)

    def list_pending_steps(self) -> tuple[StepRecord, ...]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM task_steps WHERE state = 'pending' ORDER BY task_id, step_no",
            ).fetchall()
        return tuple(_step_from_row(row) for row in rows)

    def mark_step_resolved(
        self,
        task_id: str,
        step_no: int,
        *,
        state: Literal["succeeded", "failed"],
        result_summary: str,
        changed_paths: Sequence[str],
        now: datetime,
    ) -> None:
        self.mark_step_finished(
            task_id,
            step_no,
            state=state,
            result_summary=result_summary,
            changed_paths=changed_paths,
            now=now,
        )

    def find_succeeded_step(
        self,
        task_id: str,
        tool_name: str,
        args_hash_value: str,
    ) -> StepRecord | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM task_steps
                WHERE task_id = ? AND tool_name = ? AND args_hash = ?
                  AND state = 'succeeded'
                ORDER BY step_no
                LIMIT 1
                """,
                (task_id, tool_name, args_hash_value),
            ).fetchone()
        return None if row is None else _step_from_row(row)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._database_path)) as connection:
            connection.row_factory = sqlite3.Row
            configure_connection(connection)
            yield connection


def cached_from_tool_result(result: ToolResult) -> CachedStepResult:
    return CachedStepResult(
        ok=result.ok,
        output=result.output,
        changed_paths=result.changed_paths,
        error=result.error,
    )


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def _task_from_row(row: sqlite3.Row) -> TaskRecord:
    return TaskRecord(
        task_id=str(row["task_id"]),
        session_id=str(row["session_id"]),
        request_id=str(row["request_id"]),
        goal=str(row["goal"]),
        state=row["state"],
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        max_steps=int(row["max_steps"]),
    )


def _step_from_row(row: sqlite3.Row) -> StepRecord:
    paths_raw = row["changed_paths"]
    paths = tuple(json.loads(str(paths_raw))) if paths_raw else ()
    started = row["started_at"]
    finished = row["finished_at"]
    return StepRecord(
        task_id=str(row["task_id"]),
        step_no=int(row["step_no"]),
        tool_name=str(row["tool_name"]),
        args_hash=str(row["args_hash"]),
        idempotency_key=str(row["idempotency_key"]),
        state=row["state"],
        result_summary=row["result_summary"],
        changed_paths=paths,
        started_at=None if started is None else datetime.fromisoformat(str(started)),
        finished_at=None if finished is None else datetime.fromisoformat(str(finished)),
    )

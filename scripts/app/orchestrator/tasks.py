# 파이썬 공부 | scripts/app/orchestrator/tasks.py
# 에이전트의 작업과 단계를 저장하고 중복 실행 여부를 추적합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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

# 오른쪽 식을 계산한 값을 TaskState에 대입합니다.
TaskState = Literal["pending", "running", "succeeded", "failed", "cancelled"]
# 오른쪽 식을 계산한 값을 StepState에 대입합니다.
StepState = Literal["pending", "running", "succeeded", "failed", "cancelled"]


# TaskRecord: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class TaskRecord:
    # task_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    task_id: str
    # session_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    session_id: str
    # request_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    request_id: str
    # goal: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    goal: str
    # state: TaskState 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    state: TaskState
    # created_at: datetime 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    created_at: datetime
    # updated_at: datetime 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    updated_at: datetime
    # max_steps: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    max_steps: int


# StepRecord: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class StepRecord:
    # task_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    task_id: str
    # step_no: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    step_no: int
    # tool_name: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    tool_name: str
    # args_hash: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    args_hash: str
    # idempotency_key: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    idempotency_key: str
    # state: StepState 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    state: StepState
    # result_summary: str | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    result_summary: str | None
    # changed_paths: tuple[str, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    changed_paths: tuple[str, ...]
    # started_at: datetime | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    started_at: datetime | None
    # finished_at: datetime | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    finished_at: datetime | None


# CachedStepResult: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class CachedStepResult:
    # ok: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ok: bool
    # output: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    output: str
    # changed_paths: tuple[str, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    changed_paths: tuple[str, ...]
    # error: str | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    error: str | None


# idempotency_key(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: task_id, step_no, tool_name, args_hash.
# 반환 타입 힌트: 문자열(str).
def idempotency_key(task_id: str, step_no: int, tool_name: str, args_hash: str) -> str:
    # 아래 함수()의 반환값을 payload에 대입합니다.
    payload = f"{task_id}\x00{step_no}\x00{tool_name}\x00{args_hash}".encode()
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return hashlib.sha256(payload).hexdigest()


# args_hash_for_tool(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tool_name, normalized_args.
# 반환 타입 힌트: 문자열(str).
def args_hash_for_tool(tool_name: str, normalized_args: Mapping[str, Any]) -> str:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return compute_args_hash(tool_name, dict(normalized_args))


# TaskStore: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class TaskStore:
    """Persist multi-step agent tasks and steps in SQLite."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: database_path.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, database_path: Path) -> None:
        # Path()의 반환값을 self._database_path에 대입합니다.
        self._database_path = Path(database_path)
        # RLock()의 반환값을 self._lock에 대입합니다.
        self._lock = RLock()

    # create_task(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: task_id, session_id, request_id, goal, max_steps, now.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: TaskRecord.
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
        # TaskRecord()의 반환값을 record에 대입합니다.
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
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection:
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
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
            # 데이터베이스 변경 내용을 확정합니다.
            connection.commit()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return record

    # get_task(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: task_id.
    # 반환 타입 힌트: TaskRecord | None.
    def get_task(self, task_id: str) -> TaskRecord | None:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection:
            # 아래 함수()의 반환값을 row에 대입합니다.
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        return None if row is None else _task_from_row(row)

    # update_task_state(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: task_id, state, now.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def update_task_state(self, task_id: str, state: TaskState, *, now: datetime) -> None:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection:
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            connection.execute(
                "UPDATE tasks SET state = ?, updated_at = ? WHERE task_id = ?",
                (state, _iso(now), task_id),
            )
            # 데이터베이스 변경 내용을 확정합니다.
            connection.commit()

    # create_step(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: task_id, step_no, tool_name, normalized_args.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: StepRecord.
    def create_step(
        self,
        *,
        task_id: str,
        step_no: int,
        tool_name: str,
        normalized_args: Mapping[str, Any],
    ) -> StepRecord:
        # args_hash_for_tool()의 반환값을 hashed에 대입합니다.
        hashed = args_hash_for_tool(tool_name, normalized_args)
        # idempotency_key()의 반환값을 key에 대입합니다.
        key = idempotency_key(task_id, step_no, tool_name, hashed)
        # StepRecord()의 반환값을 record에 대입합니다.
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
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection:
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
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
            # 데이터베이스 변경 내용을 확정합니다.
            connection.commit()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return record

    # get_step(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: task_id, step_no.
    # 반환 타입 힌트: StepRecord | None.
    def get_step(self, task_id: str, step_no: int) -> StepRecord | None:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection:
            # 아래 함수()의 반환값을 row에 대입합니다.
            row = connection.execute(
                "SELECT * FROM task_steps WHERE task_id = ? AND step_no = ?",
                (task_id, step_no),
            ).fetchone()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        return None if row is None else _step_from_row(row)

    # list_steps(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: task_id.
    # 반환 타입 힌트: tuple[StepRecord, ...].
    def list_steps(self, task_id: str) -> tuple[StepRecord, ...]:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection:
            # 아래 함수()의 반환값을 rows에 대입합니다.
            rows = connection.execute(
                "SELECT * FROM task_steps WHERE task_id = ? ORDER BY step_no",
                (task_id,),
            ).fetchall()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return tuple(_step_from_row(row) for row in rows)

    # mark_step_running(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: task_id, step_no, now.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def mark_step_running(self, task_id: str, step_no: int, *, now: datetime) -> None:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection:
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            connection.execute(
                """
                UPDATE task_steps
                SET state = 'running', started_at = ?
                WHERE task_id = ? AND step_no = ?
                """,
                (_iso(now), task_id, step_no),
            )
            # 데이터베이스 변경 내용을 확정합니다.
            connection.commit()

    # mark_step_finished(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: task_id, step_no, state, result_summary, changed_paths, now.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
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
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection:
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
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
            # 데이터베이스 변경 내용을 확정합니다.
            connection.commit()

    # get_succeeded_by_idempotency(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: key.
    # 반환 타입 힌트: CachedStepResult | None.
    def get_succeeded_by_idempotency(self, key: str) -> CachedStepResult | None:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection:
            # 아래 함수()의 반환값을 row에 대입합니다.
            row = connection.execute(
                """
                SELECT result_summary, changed_paths
                FROM task_steps
                WHERE idempotency_key = ? AND state = 'succeeded'
                """,
                (key,),
            ).fetchone()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: row is None.
        if row is None:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None
        # 오른쪽 식을 계산한 값을 summary에 대입합니다.
        summary = row["result_summary"] or ""
        # tuple()의 반환값을 paths에 대입합니다.
        paths = tuple(json.loads(str(row["changed_paths"])))
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CachedStepResult(ok=True, output=summary, changed_paths=paths, error=None)

    # list_running_tasks(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: tuple[TaskRecord, ...].
    def list_running_tasks(self) -> tuple[TaskRecord, ...]:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection:
            # 아래 함수()의 반환값을 rows에 대입합니다.
            rows = connection.execute(
                "SELECT * FROM tasks WHERE state = 'running' ORDER BY updated_at",
            ).fetchall()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return tuple(_task_from_row(row) for row in rows)

    # list_running_steps(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: tuple[StepRecord, ...].
    def list_running_steps(self) -> tuple[StepRecord, ...]:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection:
            # 아래 함수()의 반환값을 rows에 대입합니다.
            rows = connection.execute(
                "SELECT * FROM task_steps WHERE state = 'running' ORDER BY task_id, step_no",
            ).fetchall()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return tuple(_step_from_row(row) for row in rows)

    # list_pending_steps(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: tuple[StepRecord, ...].
    def list_pending_steps(self) -> tuple[StepRecord, ...]:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection:
            # 아래 함수()의 반환값을 rows에 대입합니다.
            rows = connection.execute(
                "SELECT * FROM task_steps WHERE state = 'pending' ORDER BY task_id, step_no",
            ).fetchall()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return tuple(_step_from_row(row) for row in rows)

    # mark_step_resolved(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: task_id, step_no, state, result_summary, changed_paths, now.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
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
        # self.mark_step_finished()을 호출해 작업을 수행합니다.
        self.mark_step_finished(
            task_id,
            step_no,
            state=state,
            result_summary=result_summary,
            changed_paths=changed_paths,
            now=now,
        )

    # find_succeeded_step(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: task_id, tool_name, args_hash_value.
    # 반환 타입 힌트: StepRecord | None.
    def find_succeeded_step(
        self,
        task_id: str,
        tool_name: str,
        args_hash_value: str,
    ) -> StepRecord | None:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection:
            # 아래 함수()의 반환값을 row에 대입합니다.
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
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        return None if row is None else _step_from_row(row)

    # _connection(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Iterator[sqlite3.Connection].
    # @contextmanager: yield 앞은 with 진입 준비, 뒤는 with 종료 시 처리입니다.
    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with closing(sqlite3.connect(self._database_path)) as connection:
            # 오른쪽 식을 계산한 값을 connection.row_factory에 대입합니다.
            connection.row_factory = sqlite3.Row
            # configure_connection()을 호출해 작업을 수행합니다.
            configure_connection(connection)
            # yield는 값을 건네고 실행을 잠시 멈춥니다. 다음 요청이 오면 이어서 진행합니다.
            yield connection


# cached_from_tool_result(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: result.
# 반환 타입 힌트: CachedStepResult.
def cached_from_tool_result(result: ToolResult) -> CachedStepResult:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return CachedStepResult(
        ok=result.ok,
        output=result.output,
        changed_paths=result.changed_paths,
        error=result.error,
    )


# _iso(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value.
# 반환 타입 힌트: 문자열(str).
def _iso(value: datetime) -> str:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return value.isoformat(timespec="milliseconds")


# _task_from_row(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: row.
# 반환 타입 힌트: TaskRecord.
def _task_from_row(row: sqlite3.Row) -> TaskRecord:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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


# _step_from_row(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: row.
# 반환 타입 힌트: StepRecord.
def _step_from_row(row: sqlite3.Row) -> StepRecord:
    # 오른쪽 식을 계산한 값을 paths_raw에 대입합니다.
    paths_raw = row["changed_paths"]
    # 오른쪽 식을 계산한 값을 paths에 대입합니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    paths = tuple(json.loads(str(paths_raw))) if paths_raw else ()
    # 오른쪽 식을 계산한 값을 started에 대입합니다.
    started = row["started_at"]
    # 오른쪽 식을 계산한 값을 finished에 대입합니다.
    finished = row["finished_at"]
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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

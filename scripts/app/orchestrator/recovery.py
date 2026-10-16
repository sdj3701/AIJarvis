# 파이썬 공부 | scripts/app/orchestrator/recovery.py
# 비정상 종료로 중단된 대화 세션과 에이전트 작업을 복구합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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

# frozenset()의 반환값을 _SIDE_EFFECT_TOOLS에 대입합니다.
_SIDE_EFFECT_TOOLS = frozenset({"create_file", "open_app", "open_folder", "open_url", "run_skill"})

# __all__에 리스트(순서가 있고 수정 가능)을 대입합니다.
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


# EventSink: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class EventSink(Protocol):
    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


# AuditWriter: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class AuditWriter(Protocol):
    # write(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: record.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def write(self, record: Mapping[str, Any]) -> None: ...


# NullAuditWriter: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class NullAuditWriter:
    # write(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: record.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def write(self, record: Mapping[str, Any]) -> None:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del record


# TaskRecoveryAction: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class TaskRecoveryAction:
    # task_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    task_id: str
    # step_no: int | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    step_no: int | None
    # action: Literal['running_needs_judgment', 'pending_needs_fresh_approval', 'left_running',
    # 'none'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    action: Literal[
        "running_needs_judgment",
        "pending_needs_fresh_approval",
        "left_running",
        "none",
    ]
    # changed_paths에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    changed_paths: tuple[str, ...] = ()
    # tool_name을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    tool_name: str | None = None


# TaskRecoveryReport: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class TaskRecoveryReport:
    # running_tasks: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    running_tasks: int
    # running_steps: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    running_steps: int
    # pending_steps: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    pending_steps: int
    # actions: tuple[TaskRecoveryAction, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    actions: tuple[TaskRecoveryAction, ...]


# SessionRecoveryAction: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class SessionRecoveryAction:
    # session_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    session_id: str
    # action: Literal['left_open', 'discarded', 'recovered', 'summarized'] 타입을 기대하는
    # 필드입니다. 이 줄만으로
    # 값이 대입되지는 않습니다.
    action: Literal["left_open", "discarded", "recovered", "summarized"]
    # summary_record_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    summary_record_id: str | None = None
    # candidate_count에 숫자 등 고정된 값을 대입합니다.
    candidate_count: int = 0


# SessionRecoveryReport: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class SessionRecoveryReport:
    # integrity_problems: tuple[str, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    integrity_problems: tuple[str, ...]
    # unfinished_count: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    unfinished_count: int
    # actions: tuple[SessionRecoveryAction, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    actions: tuple[SessionRecoveryAction, ...]


# recover_sessions(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: store, policy, events, clock, summarizer, settings, ids, sleeper, random.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: SessionRecoveryReport.
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
    # tuple()의 반환값을 problems에 대입합니다.
    problems = tuple(store.integrity_check())
    # store.unfinished_sessions()의 반환값을 unfinished에 대입합니다.
    unfinished = store.unfinished_sessions()
    # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
    events.emit(
        "recovery.start",
        {
            "unfinished_sessions": len(unfinished),
            "tmp_files": 0,
            "running_steps": 0,
            "integrity_problems": len(problems),
        },
    )

    # actions에 리스트(순서가 있고 수정 가능)을 대입합니다.
    actions: list[SessionRecoveryAction] = []
    # for 반복문: 대상의 항목을 하나씩 session에 대입하며 아래 블록을 실행합니다.
    for session in unfinished:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: policy == 'prompt'.
        if policy == "prompt":
            # 리스트 끝에 항목 하나를 추가합니다.
            actions.append(SessionRecoveryAction(session.session_id, "left_open"))
            # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
            events.emit(
                "recovery.result",
                {
                    "action": "left_open",
                    "session_id": session.session_id,
                    "quarantined": None,
                    "restored_turns": session.turn_count,
                },
            )
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue

        # 오른쪽 식을 계산한 값을 reason에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        reason: EndReason = "discarded" if policy == "discard" else "crash_recovered"
        # summary_record_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        summary_record_id: str | None = None
        # candidate_count에 숫자 등 고정된 값을 대입합니다.
        candidate_count = 0
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if (
            policy == "auto"
            and summarizer is not None
            and settings is not None
            and ids is not None
            and sleeper is not None
            and random is not None
        ):
            # ids.new()의 반환값을 turn_id에 대입합니다.
            turn_id = ids.new("turn")
            # RequestContext()의 반환값을 ctx에 대입합니다.
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
            # summarizer.summarize_session()의 반환값을 summary에 대입합니다.
            summary = summarizer.summarize_session(session.session_id, ctx=ctx)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: summary is not None.
            if summary is not None:
                # 오른쪽 식을 계산한 값을 summary_record_id에 대입합니다.
                summary_record_id = summary.summary_record_id
                # len()의 반환값을 candidate_count에 대입합니다.
                candidate_count = len(summary.fact_candidates)

        # store.end_session()을 호출해 작업을 수행합니다.
        store.end_session(session.session_id, ended_at=clock.now(), reason=reason)
        # 오른쪽 식을 계산한 값을 action_name에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        action_name: Literal["discarded", "recovered", "summarized"] = (
            "discarded"
            if policy == "discard"
            else "summarized"
            if summary_record_id
            else "recovered"
        )
        # 리스트 끝에 항목 하나를 추가합니다.
        actions.append(
            SessionRecoveryAction(
                session.session_id,
                action_name,
                summary_record_id=summary_record_id,
                candidate_count=candidate_count,
            )
        )
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
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

    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not actions.
    if not actions:
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        events.emit(
            "recovery.result",
            {
                "action": "none",
                "session_id": None,
                "quarantined": None,
                "restored_turns": 0,
            },
        )

    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return SessionRecoveryReport(
        integrity_problems=problems,
        unfinished_count=len(unfinished),
        actions=tuple(actions),
    )


# recover_tasks(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: task_store, events.
# 반환 타입 힌트: TaskRecoveryReport.
def recover_tasks(task_store: TaskStore, events: EventSink) -> TaskRecoveryReport:
    """Surface running agent tasks/steps; never auto re-execute side effects."""
    # task_store.list_running_tasks()의 반환값을 running_tasks에 대입합니다.
    running_tasks = task_store.list_running_tasks()
    # task_store.list_running_steps()의 반환값을 running_steps에 대입합니다.
    running_steps = task_store.list_running_steps()
    # task_store.list_pending_steps()의 반환값을 pending_steps에 대입합니다.
    pending_steps = task_store.list_pending_steps()
    # actions에 리스트(순서가 있고 수정 가능)을 대입합니다.
    actions: list[TaskRecoveryAction] = []

    # for 반복문: 대상의 항목을 하나씩 step에 대입하며 아래 블록을 실행합니다.
    for step in pending_steps:
        # TaskRecoveryAction()의 반환값을 action에 대입합니다.
        action = TaskRecoveryAction(
            task_id=step.task_id,
            step_no=step.step_no,
            action="pending_needs_fresh_approval",
            tool_name=step.tool_name,
        )
        # 리스트 끝에 항목 하나를 추가합니다.
        actions.append(action)
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
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

    # for 반복문: 대상의 항목을 하나씩 step에 대입하며 아래 블록을 실행합니다.
    for step in running_steps:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: step.tool_name in _SIDE_EFFECT_TOOLS.
        if step.tool_name in _SIDE_EFFECT_TOOLS:
            # TaskRecoveryAction()의 반환값을 action에 대입합니다.
            action = TaskRecoveryAction(
                task_id=step.task_id,
                step_no=step.step_no,
                action="running_needs_judgment",
                changed_paths=step.changed_paths,
                tool_name=step.tool_name,
            )
            # 리스트 끝에 항목 하나를 추가합니다.
            actions.append(action)
            # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
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
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # 리스트 끝에 항목 하나를 추가합니다.
            actions.append(
                TaskRecoveryAction(
                    task_id=step.task_id,
                    step_no=step.step_no,
                    action="left_running",
                    tool_name=step.tool_name,
                )
            )
            # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
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

    # for 반복문: 대상의 항목을 하나씩 task에 대입하며 아래 블록을 실행합니다.
    for task in running_tasks:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not any((action.task_id ==
        # task.task_id for action in
        # actions)).
        if not any(action.task_id == task.task_id for action in actions):
            # 리스트 끝에 항목 하나를 추가합니다.
            actions.append(
                TaskRecoveryAction(task_id=task.task_id, step_no=None, action="left_running")
            )

    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not actions.
    if not actions:
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
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

    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return TaskRecoveryReport(
        running_tasks=len(running_tasks),
        running_steps=len(running_steps),
        pending_steps=len(pending_steps),
        actions=tuple(actions),
    )

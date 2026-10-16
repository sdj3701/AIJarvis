# 파이썬 공부 | scripts/tests/integration/test_agent_recovery.py
# agent_recovery 관련 여러 기능의 연결을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Phase 5 recovery tests for agent tasks and steps."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.orchestrator.recovery import recover_tasks
from tests.helpers.phase5_app import Phase5App, build_phase5_app

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase5
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


# RecordingEvents: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class RecordingEvents:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # self.items에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.items: list[tuple[str, dict]] = []

    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload) -> None:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.items.append((event_type, dict(payload)))


# _seed_succeeded_create_file(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: app, filename.
# 반환 타입 힌트: 문자열(str).
def _seed_succeeded_create_file(app: Phase5App, filename: str) -> str:
    # 오른쪽 식을 계산한 값을 store에 대입합니다.
    store = app.runtime.task_store
    # app.runtime.ids.new()의 반환값을 task_id에 대입합니다.
    task_id = app.runtime.ids.new("task")
    # store.create_task()을 호출해 작업을 수행합니다.
    store.create_task(
        task_id=task_id,
        session_id=app.chat.session_id or app.runtime.ids.new("ses"),
        request_id=app.runtime.ids.new("req"),
        goal="주제를 검색해서 notes에 저장한 뒤 폴더를 열어줘.",
        max_steps=8,
        now=NOW,
    )
    # normalized에 딕셔너리(키와 값의 쌍)을 대입합니다.
    normalized = {
        "root": "notes",
        "relative_path": filename,
        "content": "already written",
        "overwrite": False,
    }
    # store.create_step()을 호출해 작업을 수행합니다.
    store.create_step(
        task_id=task_id,
        step_no=1,
        tool_name="create_file",
        normalized_args=normalized,
    )
    # store.mark_step_running()을 호출해 작업을 수행합니다.
    store.mark_step_running(task_id, 1, now=NOW)
    # store.mark_step_finished()을 호출해 작업을 수행합니다.
    store.mark_step_finished(
        task_id,
        1,
        state="succeeded",
        result_summary="already created",
        changed_paths=(str(app.data_root / "docs" / "notes" / filename),),
        now=NOW,
    )
    # store.update_task_state()을 호출해 작업을 수행합니다.
    store.update_task_state(task_id, "running", now=NOW)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return task_id


# pytest가 test_no_duplicate_write_on_resume()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_no_duplicate_write_on_resume(config_dir) -> None:
    # 오른쪽 식을 계산한 값을 filename에 대입합니다.
    # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
    filename = f"resume-{uuid.uuid4().hex[:8]}.md"
    from decimal import Decimal

    from app.llm.base import LLMUsage
    from app.llm.fake import FakeLLMClient

    # 아래 함수()의 반환값을 llm에 대입합니다.
    llm = (
        FakeLLMClient()
        .call_tool("open_folder", root="notes", relative_path="")
        .reply("done", usage=LLMUsage(1, 1, Decimal("0"), 1))
    )
    # build_phase5_app()의 반환값을 app에 대입합니다.
    app = build_phase5_app(config_dir, llm=llm)
    # _seed_succeeded_create_file()의 반환값을 task_id에 대입합니다.
    task_id = _seed_succeeded_create_file(app, filename)
    # 오른쪽 식을 계산한 값을 target에 대입합니다.
    target = app.data_root / "docs" / "notes" / filename
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    target.parent.mkdir(parents=True, exist_ok=True)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    target.write_text("already written", encoding="utf-8")
    # calls_before에 숫자 등 고정된 값을 대입합니다.
    calls_before = 0
    # 오른쪽 식을 계산한 값을 original에 대입합니다.
    original = app.runtime.tool_runner.execute

    # counting_execute(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: call, ctx, ticket.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    def counting_execute(call, *, ctx, ticket=None):
        # 바로 바깥쪽 함수 범위에 있는 변수를 이 함수에서 다시 대입할 수 있게 합니다.
        nonlocal calls_before
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: call.name == 'create_file'.
        if call.name == "create_file":
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            calls_before += 1
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return original(call, ctx=ctx, ticket=ticket)

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch.object(app.runtime.tool_runner, "execute", side_effect=counting_execute):
        # app.chat.continue_task()의 반환값을 outcome에 대입합니다.
        outcome = app.chat.continue_task(task_id)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert calls_before == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert target.read_text(encoding="utf-8") == "already written"


# pytest가 test_running_step_not_auto_rerun()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_running_step_not_auto_rerun(config_dir) -> None:
    # build_phase5_app()의 반환값을 app에 대입합니다.
    app = build_phase5_app(config_dir)
    # 오른쪽 식을 계산한 값을 store에 대입합니다.
    store = app.runtime.task_store
    # app.runtime.ids.new()의 반환값을 task_id에 대입합니다.
    task_id = app.runtime.ids.new("task")
    # store.create_task()을 호출해 작업을 수행합니다.
    store.create_task(
        task_id=task_id,
        session_id=app.chat.session_id or app.runtime.ids.new("ses"),
        request_id=app.runtime.ids.new("req"),
        goal="notes에 저장해줘",
        max_steps=3,
        now=NOW,
    )
    # normalized에 딕셔너리(키와 값의 쌍)을 대입합니다.
    normalized = {"root": "notes", "relative_path": "running.md", "content": "x"}
    # store.create_step()을 호출해 작업을 수행합니다.
    store.create_step(
        task_id=task_id,
        step_no=1,
        tool_name="create_file",
        normalized_args=normalized,
    )
    # store.mark_step_running()을 호출해 작업을 수행합니다.
    store.mark_step_running(task_id, 1, now=NOW)
    # RecordingEvents()의 반환값을 events에 대입합니다.
    events = RecordingEvents()
    # recover_tasks()의 반환값을 report에 대입합니다.
    report = recover_tasks(store, events)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert report.running_steps == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any(action.action == "running_needs_judgment" for action in report.actions)
    # calls에 숫자 등 고정된 값을 대입합니다.
    calls = 0
    # 오른쪽 식을 계산한 값을 original에 대입합니다.
    original = app.runtime.tool_runner.execute

    # counting_execute(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: call, ctx, ticket.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    def counting_execute(call, *, ctx, ticket=None):
        # 바로 바깥쪽 함수 범위에 있는 변수를 이 함수에서 다시 대입할 수 있게 합니다.
        nonlocal calls
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        calls += 1
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return original(call, ctx=ctx, ticket=ticket)

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch.object(app.runtime.tool_runner, "execute", side_effect=counting_execute):
        # app.chat.continue_task()을 호출해 작업을 수행합니다.
        app.chat.continue_task(task_id)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert calls == 0
    # app.chat.mark_step_resolved()을 호출해 작업을 수행합니다.
    app.chat.mark_step_resolved(
        task_id,
        1,
        succeeded=True,
        result_summary="user confirmed write",
        changed_paths=(str(app.data_root / "docs" / "notes" / "running.md"),),
    )
    # store.get_step()의 반환값을 step에 대입합니다.
    step = store.get_step(task_id, 1)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert step is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert step.state == "succeeded"

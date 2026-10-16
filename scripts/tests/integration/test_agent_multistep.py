# 파이썬 공부 | scripts/tests/integration/test_agent_multistep.py
# agent_multistep 관련 여러 기능의 연결을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Phase 5 multi-step agent integration tests."""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest

from app.core.canonical import args_hash
from app.llm.fake import FakeLLMClient
from app.orchestrator.agent import format_step_breakdown, goal_permits_side_effect
from app.orchestrator.tasks import StepRecord, idempotency_key
from tests.fakes.clock import SteppingClock
from tests.helpers.phase5_app import (
    NOW,
    Phase5App,
    build_phase5_app,
    golden_task_script,
    inject_create_file_script,
)

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase5


# _latest_task_id(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: app.
# 반환 타입 힌트: 문자열(str).
def _latest_task_id(app: Phase5App) -> str:
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with app.runtime.task_store._connection() as connection:
        # 아래 함수()의 반환값을 row에 대입합니다.
        row = connection.execute(
            "SELECT task_id FROM tasks ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert row is not None
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return str(row["task_id"])


# pytest가 test_search_summarize_save_open()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_search_summarize_save_open(config_dir) -> None:
    # 오른쪽 식을 계산한 값을 filename에 대입합니다.
    # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
    filename = f"summary-{uuid.uuid4().hex[:8]}.md"
    # build_phase5_app()의 반환값을 app에 대입합니다.
    app = build_phase5_app(config_dir, llm=golden_task_script(filename))
    # text에 문자열을 대입합니다.
    text = "주제를 검색해서 근거와 함께 요약하고 notes에 저장한 뒤 폴더를 열어줘."
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_folder.os.startfile"):
        # app.handle()의 반환값을 response에 대입합니다.
        response = app.handle(text)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "완료:" in response
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "create_file" in response
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "open_folder" in response
    # 오른쪽 식을 계산한 값을 target에 대입합니다.
    target = app.data_root / "docs" / "notes" / filename
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert target.is_file()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "Jarvis" in target.read_text(encoding="utf-8")
    # 오른쪽 식을 계산한 값을 task_id에 대입합니다.
    task_id = app.last_task_id
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert task_id is not None
    # app.runtime.task_store.list_steps()의 반환값을 steps에 대입합니다.
    steps = app.runtime.task_store.list_steps(task_id)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(steps) >= 3
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert steps[0].tool_name == "web_search"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any(step.tool_name == "create_file" and step.state == "succeeded" for step in steps)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any(step.tool_name == "open_folder" and step.state == "succeeded" for step in steps)


# pytest가 test_native_tool_call_preserves_assistant_and_tool_history()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_native_tool_call_preserves_assistant_and_tool_history(config_dir) -> None:
    # 아래 함수()의 반환값을 llm에 대입합니다.
    llm = FakeLLMClient().call_tool("web_search", query="Jarvis").reply("요약했습니다.")
    # build_phase5_app()의 반환값을 app에 대입합니다.
    app = build_phase5_app(
        config_dir,
        llm=llm,
        native_tool_calling_enabled=True,
    )

    # app.chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = app.chat.handle_turn("내일 일정 요약해줘")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.ok is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "요약했습니다." in outcome.text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(llm.calls) == 2
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert all(specs for specs in llm.tool_specs)
    # 오른쪽 식을 계산한 값을 follow_up에 대입합니다.
    follow_up = llm.calls[1]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [message.role for message in follow_up[-3:]] == ["user", "assistant", "tool"]
    # 오른쪽 식을 계산한 값을 assistant_call에 대입합니다.
    assistant_call = follow_up[-2]
    # 오른쪽 식을 계산한 값을 tool_result에 대입합니다.
    tool_result = follow_up[-1]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert assistant_call.content == ""
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert assistant_call.tool_calls[0].name == "web_search"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert tool_result.name == "web_search"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert tool_result.tool_call_id == assistant_call.tool_calls[0].id


# pytest가 test_native_tool_call_keeps_history_across_approval_resume()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_native_tool_call_keeps_history_across_approval_resume(config_dir) -> None:
    # 오른쪽 식을 계산한 값을 filename에 대입합니다.
    # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
    filename = f"native-{uuid.uuid4().hex[:8]}.md"
    # 아래 함수()의 반환값을 llm에 대입합니다.
    llm = (
        FakeLLMClient()
        .call_tool("create_file", root="notes", relative_path=filename, content="내용")
        .reply("저장했습니다.")
    )
    # build_phase5_app()의 반환값을 app에 대입합니다.
    app = build_phase5_app(
        config_dir,
        llm=llm,
        native_tool_calling_enabled=True,
    )

    # app.handle()의 반환값을 response에 대입합니다.
    response = app.handle(f"notes에 {filename} 파일을 저장해줘")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "저장했습니다." in response
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert (app.data_root / "docs" / "notes" / filename).is_file()
    # 오른쪽 식을 계산한 값을 follow_up에 대입합니다.
    follow_up = llm.calls[1]
    # 오른쪽 식을 계산한 값을 assistant_call에 대입합니다.
    assistant_call = follow_up[-2]
    # 오른쪽 식을 계산한 값을 tool_result에 대입합니다.
    tool_result = follow_up[-1]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [message.role for message in follow_up[-3:]] == ["user", "assistant", "tool"]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert assistant_call.tool_calls[0].name == "create_file"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert tool_result.tool_call_id == assistant_call.tool_calls[0].id


# pytest가 test_stops_at_max_steps()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_stops_at_max_steps(config_dir) -> None:
    # build_phase5_app()의 반환값을 app에 대입합니다.
    app = build_phase5_app(config_dir, llm=golden_task_script(), max_steps=2)
    # app.handle()의 반환값을 response에 대입합니다.
    response = app.handle("주제를 검색해서 notes에 저장한 뒤 폴더를 열어줘.")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "최대 2단계" in response or "미실행:" in response
    # app.runtime.task_store.list_steps()의 반환값을 steps에 대입합니다.
    steps = app.runtime.task_store.list_steps(_latest_task_id(app))
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(steps) <= 2


# pytest가 test_task_timeout_leaves_remaining_steps_unrun()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_task_timeout_leaves_remaining_steps_unrun(config_dir) -> None:
    # build_phase5_app()의 반환값을 app에 대입합니다.
    app = build_phase5_app(
        config_dir,
        llm=golden_task_script(),
        total_timeout_s=0.001,
        clock=SteppingClock(
            NOW,
            step=timedelta(seconds=1),
        ),
    )
    # app.handle()의 반환값을 response에 대입합니다.
    response = app.handle("주제를 검색해서 notes에 저장한 뒤 폴더를 열어줘.")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "미실행:" in response or "시간" in response


# pytest가 test_step_timeout_stops_before_tool_execution()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_step_timeout_stops_before_tool_execution(config_dir) -> None:
    # build_phase5_app()의 반환값을 app에 대입합니다.
    app = build_phase5_app(
        config_dir,
        llm=golden_task_script("timeout.md"),
        step_timeout_s=0.5,
        total_timeout_s=30,
        clock=SteppingClock(
            NOW,
            step=timedelta(seconds=1),
        ),
    )

    # app.handle()의 반환값을 response에 대입합니다.
    response = app.handle("주제를 검색해서 notes에 저장한 뒤 폴더를 열어줘.")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "단계 실행 시간이 초과" in response
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not (app.data_root / "docs" / "notes" / "timeout.md").exists()


# pytest가 test_untrusted_search_cannot_spawn_side_effect_goal()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_untrusted_search_cannot_spawn_side_effect_goal(config_dir) -> None:
    # build_phase5_app()의 반환값을 app에 대입합니다.
    app = build_phase5_app(config_dir, llm=inject_create_file_script())
    # app.handle()의 반환값을 response에 대입합니다.
    response = app.handle("양자컴퓨팅 주제를 조사해줘")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "부작용" in response or "실행하지" in response or "거부" in response
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not (app.data_root / "docs" / "notes" / "evil.md").exists()


# pytest가 test_approval_deny_stops_subsequent_steps()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_approval_deny_stops_subsequent_steps(config_dir) -> None:
    # 오른쪽 식을 계산한 값을 filename에 대입합니다.
    # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
    filename = f"deny-{uuid.uuid4().hex[:8]}.md"
    # build_phase5_app()의 반환값을 app에 대입합니다.
    app = build_phase5_app(config_dir, llm=golden_task_script(filename))
    # app.handle()의 반환값을 response에 대입합니다.
    response = app.handle(
        "주제를 검색해서 notes에 저장한 뒤 폴더를 열어줘.",
        approval="deny",
    )
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "실행하지" in response
    # app.runtime.task_store.list_steps()의 반환값을 steps에 대입합니다.
    steps = app.runtime.task_store.list_steps(_latest_task_id(app))
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not any(step.tool_name == "open_folder" and step.state == "succeeded" for step in steps)


# pytest가 test_approval_pending_step_is_not_marked_running()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_approval_pending_step_is_not_marked_running(config_dir) -> None:
    # build_phase5_app()의 반환값을 app에 대입합니다.
    app = build_phase5_app(config_dir, llm=golden_task_script("pending.md"))
    # app.chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = app.chat.handle_turn(
        "주제를 검색해서 notes에 저장한 뒤 폴더를 열어줘."
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.pending_approval is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.task_id is not None
    # app.runtime.task_store.list_steps()의 반환값을 steps에 대입합니다.
    steps = app.runtime.task_store.list_steps(outcome.task_id)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert steps[-1].tool_name == "create_file"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert steps[-1].state == "pending"


# pytest가 test_step_status_breakdown_in_final_text()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_step_status_breakdown_in_final_text() -> None:
    # steps에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    steps = (
        StepRecord(
            task_id="task_01",
            step_no=1,
            tool_name="web_search",
            args_hash="abc",
            idempotency_key="key1",
            state="succeeded",
            result_summary="ok",
            changed_paths=(),
            started_at=None,
            finished_at=None,
        ),
        StepRecord(
            task_id="task_01",
            step_no=2,
            tool_name="create_file",
            args_hash="def",
            idempotency_key="key2",
            state="failed",
            result_summary="fail",
            changed_paths=(),
            started_at=None,
            finished_at=None,
        ),
    )
    # format_step_breakdown()의 반환값을 text에 대입합니다.
    text = format_step_breakdown(steps, max_steps=3)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "완료: 1.web_search" in text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "실패: 2.create_file" in text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "3" in text


# pytest가 test_goal_permits_side_effect_requires_user_intent()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_goal_permits_side_effect_requires_user_intent() -> None:
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert goal_permits_side_effect("양자컴퓨팅 검색해줘", "create_file") is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert goal_permits_side_effect("검색 후 notes에 저장해줘", "create_file") is True


# pytest가 test_idempotency_key_uniqueness()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_idempotency_key_uniqueness() -> None:
    # idempotency_key()의 반환값을 first에 대입합니다.
    first = idempotency_key("task_a", 1, "create_file", "hash1")
    # idempotency_key()의 반환값을 second에 대입합니다.
    second = idempotency_key("task_a", 2, "create_file", "hash1")
    # idempotency_key()의 반환값을 third에 대입합니다.
    third = idempotency_key("task_a", 1, "create_file", "hash2")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first != second
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first != third


# pytest가 test_task_store_idempotency_cache()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: phase5_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_task_store_idempotency_cache(phase5_app: Phase5App) -> None:
    # 오른쪽 식을 계산한 값을 store에 대입합니다.
    store = phase5_app.runtime.task_store
    # phase5_app.runtime.clock.now()의 반환값을 now에 대입합니다.
    now = phase5_app.runtime.clock.now()
    # phase5_app.runtime.ids.new()의 반환값을 task_id에 대입합니다.
    task_id = phase5_app.runtime.ids.new("task")
    # 오른쪽 식을 계산한 값을 session_id에 대입합니다.
    session_id = phase5_app.chat.session_id or phase5_app.runtime.ids.new("ses")
    # phase5_app.runtime.ids.new()의 반환값을 request_id에 대입합니다.
    request_id = phase5_app.runtime.ids.new("req")
    # store.create_task()을 호출해 작업을 수행합니다.
    store.create_task(
        task_id=task_id,
        session_id=session_id,
        request_id=request_id,
        goal="test",
        max_steps=3,
        now=now,
    )
    # normalized에 딕셔너리(키와 값의 쌍)을 대입합니다.
    normalized = {"root": "notes", "relative_path": "a.md", "content": "x"}
    # store.create_step()을 호출해 작업을 수행합니다.
    store.create_step(
        task_id=task_id,
        step_no=1,
        tool_name="create_file",
        normalized_args=normalized,
    )
    # args_hash()의 반환값을 hashed에 대입합니다.
    hashed = args_hash("create_file", normalized)
    # idempotency_key()의 반환값을 key에 대입합니다.
    key = idempotency_key(task_id, 1, "create_file", hashed)
    # store.mark_step_running()을 호출해 작업을 수행합니다.
    store.mark_step_running(task_id, 1, now=now)
    # store.mark_step_finished()을 호출해 작업을 수행합니다.
    store.mark_step_finished(
        task_id,
        1,
        state="succeeded",
        result_summary="created",
        changed_paths=("notes/a.md",),
        now=now,
    )
    # store.get_succeeded_by_idempotency()의 반환값을 cached에 대입합니다.
    cached = store.get_succeeded_by_idempotency(key)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert cached is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert cached.output == "created"

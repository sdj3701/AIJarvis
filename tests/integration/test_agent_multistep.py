"""Phase 5 multi-step agent integration tests."""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest

from app.core.canonical import args_hash
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

pytestmark = pytest.mark.phase5


def _latest_task_id(app: Phase5App) -> str:
    with app.runtime.task_store._connection() as connection:
        row = connection.execute(
            "SELECT task_id FROM tasks ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    return str(row["task_id"])


def test_search_summarize_save_open(config_dir) -> None:
    filename = f"summary-{uuid.uuid4().hex[:8]}.md"
    app = build_phase5_app(config_dir, llm=golden_task_script(filename))
    text = "주제를 검색해서 근거와 함께 요약하고 notes에 저장한 뒤 폴더를 열어줘."
    with patch("app.tools.impl.open_folder.os.startfile"):
        response = app.handle(text)
    assert "완료:" in response
    assert "create_file" in response
    assert "open_folder" in response
    target = app.data_root / "docs" / "notes" / filename
    assert target.is_file()
    assert "Jarvis" in target.read_text(encoding="utf-8")
    task_id = app.last_task_id
    assert task_id is not None
    steps = app.runtime.task_store.list_steps(task_id)
    assert len(steps) >= 3
    assert steps[0].tool_name == "web_search"
    assert any(step.tool_name == "create_file" and step.state == "succeeded" for step in steps)
    assert any(step.tool_name == "open_folder" and step.state == "succeeded" for step in steps)


def test_stops_at_max_steps(config_dir) -> None:
    app = build_phase5_app(config_dir, llm=golden_task_script(), max_steps=2)
    response = app.handle("주제를 검색해서 notes에 저장한 뒤 폴더를 열어줘.")
    assert "최대 2단계" in response or "미실행:" in response
    steps = app.runtime.task_store.list_steps(_latest_task_id(app))
    assert len(steps) <= 2


def test_task_timeout_leaves_remaining_steps_unrun(config_dir) -> None:
    app = build_phase5_app(
        config_dir,
        llm=golden_task_script(),
        total_timeout_s=0.001,
        clock=SteppingClock(
            NOW,
            step=timedelta(seconds=1),
        ),
    )
    response = app.handle("주제를 검색해서 notes에 저장한 뒤 폴더를 열어줘.")
    assert "미실행:" in response or "시간" in response


def test_step_timeout_stops_before_tool_execution(config_dir) -> None:
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

    response = app.handle("주제를 검색해서 notes에 저장한 뒤 폴더를 열어줘.")

    assert "단계 실행 시간이 초과" in response
    assert not (app.data_root / "docs" / "notes" / "timeout.md").exists()


def test_untrusted_search_cannot_spawn_side_effect_goal(config_dir) -> None:
    app = build_phase5_app(config_dir, llm=inject_create_file_script())
    response = app.handle("양자컴퓨팅 주제를 조사해줘")
    assert "부작용" in response or "실행하지" in response or "거부" in response
    assert not (app.data_root / "docs" / "notes" / "evil.md").exists()


def test_approval_deny_stops_subsequent_steps(config_dir) -> None:
    filename = f"deny-{uuid.uuid4().hex[:8]}.md"
    app = build_phase5_app(config_dir, llm=golden_task_script(filename))
    response = app.handle(
        "주제를 검색해서 notes에 저장한 뒤 폴더를 열어줘.",
        approval="deny",
    )
    assert "실행하지" in response
    steps = app.runtime.task_store.list_steps(_latest_task_id(app))
    assert not any(step.tool_name == "open_folder" and step.state == "succeeded" for step in steps)


def test_approval_pending_step_is_not_marked_running(config_dir) -> None:
    app = build_phase5_app(config_dir, llm=golden_task_script("pending.md"))
    outcome = app.chat.handle_turn(
        "주제를 검색해서 notes에 저장한 뒤 폴더를 열어줘."
    )

    assert outcome.pending_approval is not None
    assert outcome.task_id is not None
    steps = app.runtime.task_store.list_steps(outcome.task_id)
    assert steps[-1].tool_name == "create_file"
    assert steps[-1].state == "pending"


def test_step_status_breakdown_in_final_text() -> None:
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
    text = format_step_breakdown(steps, max_steps=3)
    assert "완료: 1.web_search" in text
    assert "실패: 2.create_file" in text
    assert "3" in text


def test_goal_permits_side_effect_requires_user_intent() -> None:
    assert goal_permits_side_effect("양자컴퓨팅 검색해줘", "create_file") is False
    assert goal_permits_side_effect("검색 후 notes에 저장해줘", "create_file") is True


def test_idempotency_key_uniqueness() -> None:
    first = idempotency_key("task_a", 1, "create_file", "hash1")
    second = idempotency_key("task_a", 2, "create_file", "hash1")
    third = idempotency_key("task_a", 1, "create_file", "hash2")
    assert first != second
    assert first != third


def test_task_store_idempotency_cache(phase5_app: Phase5App) -> None:
    store = phase5_app.runtime.task_store
    now = phase5_app.runtime.clock.now()
    task_id = phase5_app.runtime.ids.new("task")
    session_id = phase5_app.chat.session_id or phase5_app.runtime.ids.new("ses")
    request_id = phase5_app.runtime.ids.new("req")
    store.create_task(
        task_id=task_id,
        session_id=session_id,
        request_id=request_id,
        goal="test",
        max_steps=3,
        now=now,
    )
    normalized = {"root": "notes", "relative_path": "a.md", "content": "x"}
    store.create_step(
        task_id=task_id,
        step_no=1,
        tool_name="create_file",
        normalized_args=normalized,
    )
    hashed = args_hash("create_file", normalized)
    key = idempotency_key(task_id, 1, "create_file", hashed)
    store.mark_step_running(task_id, 1, now=now)
    store.mark_step_finished(
        task_id,
        1,
        state="succeeded",
        result_summary="created",
        changed_paths=("notes/a.md",),
        now=now,
    )
    cached = store.get_succeeded_by_idempotency(key)
    assert cached is not None
    assert cached.output == "created"

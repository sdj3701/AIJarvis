"""Phase 5 recovery tests for agent tasks and steps."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.orchestrator.recovery import recover_tasks
from tests.helpers.phase5_app import Phase5App, build_phase5_app

pytestmark = pytest.mark.phase5
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


class RecordingEvents:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload) -> None:
        self.items.append((event_type, dict(payload)))


def _seed_succeeded_create_file(app: Phase5App, filename: str) -> str:
    store = app.runtime.task_store
    task_id = app.runtime.ids.new("task")
    store.create_task(
        task_id=task_id,
        session_id=app.chat.session_id or app.runtime.ids.new("ses"),
        request_id=app.runtime.ids.new("req"),
        goal="주제를 검색해서 notes에 저장한 뒤 폴더를 열어줘.",
        max_steps=8,
        now=NOW,
    )
    normalized = {
        "root": "notes",
        "relative_path": filename,
        "content": "already written",
        "overwrite": False,
    }
    store.create_step(
        task_id=task_id,
        step_no=1,
        tool_name="create_file",
        normalized_args=normalized,
    )
    store.mark_step_running(task_id, 1, now=NOW)
    store.mark_step_finished(
        task_id,
        1,
        state="succeeded",
        result_summary="already created",
        changed_paths=(str(app.data_root / "docs" / "notes" / filename),),
        now=NOW,
    )
    store.update_task_state(task_id, "running", now=NOW)
    return task_id


def test_no_duplicate_write_on_resume(config_dir) -> None:
    filename = f"resume-{uuid.uuid4().hex[:8]}.md"
    from decimal import Decimal

    from app.llm.base import LLMUsage
    from app.llm.fake import FakeLLMClient

    llm = (
        FakeLLMClient()
        .call_tool("open_folder", root="notes", relative_path="")
        .reply("done", usage=LLMUsage(1, 1, Decimal("0"), 1))
    )
    app = build_phase5_app(config_dir, llm=llm)
    task_id = _seed_succeeded_create_file(app, filename)
    target = app.data_root / "docs" / "notes" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("already written", encoding="utf-8")
    calls_before = 0
    original = app.runtime.tool_runner.execute

    def counting_execute(call, *, ctx, ticket=None):
        nonlocal calls_before
        if call.name == "create_file":
            calls_before += 1
        return original(call, ctx=ctx, ticket=ticket)

    with patch.object(app.runtime.tool_runner, "execute", side_effect=counting_execute):
        outcome = app.chat.continue_task(task_id)
    assert calls_before == 0
    assert outcome.text
    assert target.read_text(encoding="utf-8") == "already written"


def test_running_step_not_auto_rerun(config_dir) -> None:
    app = build_phase5_app(config_dir)
    store = app.runtime.task_store
    task_id = app.runtime.ids.new("task")
    store.create_task(
        task_id=task_id,
        session_id=app.chat.session_id or app.runtime.ids.new("ses"),
        request_id=app.runtime.ids.new("req"),
        goal="notes에 저장해줘",
        max_steps=3,
        now=NOW,
    )
    normalized = {"root": "notes", "relative_path": "running.md", "content": "x"}
    store.create_step(
        task_id=task_id,
        step_no=1,
        tool_name="create_file",
        normalized_args=normalized,
    )
    store.mark_step_running(task_id, 1, now=NOW)
    events = RecordingEvents()
    report = recover_tasks(store, events)
    assert report.running_steps == 1
    assert any(action.action == "running_needs_judgment" for action in report.actions)
    calls = 0
    original = app.runtime.tool_runner.execute

    def counting_execute(call, *, ctx, ticket=None):
        nonlocal calls
        calls += 1
        return original(call, ctx=ctx, ticket=ticket)

    with patch.object(app.runtime.tool_runner, "execute", side_effect=counting_execute):
        app.chat.continue_task(task_id)
    assert calls == 0
    app.chat.mark_step_resolved(
        task_id,
        1,
        succeeded=True,
        result_summary="user confirmed write",
        changed_paths=(str(app.data_root / "docs" / "notes" / "running.md"),),
    )
    step = store.get_step(task_id, 1)
    assert step is not None
    assert step.state == "succeeded"

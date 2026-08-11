"""Approval ticket binding and reuse rules."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.errors import ApprovalMismatch
from app.llm.base import ToolCall
from tests.helpers.phase4_app import NOW, Phase4App

pytestmark = [pytest.mark.phase4, pytest.mark.security]


def test_args_change_invalidates_ticket(phase4_app: Phase4App) -> None:
    chat = phase4_app.chat
    context = _ctx(phase4_app)
    call = ToolCall(
        id="t1",
        name="create_file",
        arguments={
            "root": "notes",
            "relative_path": "a.md",
            "content": "hello",
        },
    )
    outcome = chat.execute_tool_call(call, ctx=context)
    assert outcome.pending_approval is not None
    verdict = outcome.pending_approval
    ticket = phase4_app.runtime.approval_store.grant(
        verdict,
        ctx=context,
        method="user_text",
    )
    changed = ToolCall(
        id="t2",
        name="create_file",
        arguments={
            "root": "notes",
            "relative_path": "b.md",
            "content": "hello",
        },
    )
    with pytest.raises(ApprovalMismatch):
        phase4_app.runtime.tool_runner.execute(
            changed,
            ctx=context,
            ticket=ticket,
        )


def test_ticket_reuse_denied(phase4_app: Phase4App) -> None:
    import uuid

    name = f"once-{uuid.uuid4().hex[:8]}.md"
    notes = phase4_app.data_root / "docs" / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    call = ToolCall(
        id="reuse",
        name="create_file",
        arguments={"root": "notes", "relative_path": name, "content": "x"},
    )
    outcome = phase4_app.chat.execute_tool_call(call, ctx=_ctx(phase4_app))
    verdict = outcome.pending_approval
    assert verdict is not None
    ticket = phase4_app.runtime.approval_store.grant(
        verdict,
        ctx=_ctx(phase4_app),
        method="user_text",
    )
    phase4_app.runtime.tool_runner.execute(call, ctx=_ctx(phase4_app), ticket=ticket)
    with pytest.raises(ApprovalMismatch):
        phase4_app.runtime.approval_store.consume(
            ticket.id,
            tool_name=call.name,
            args_hash=verdict.args_hash,
            now=NOW,
        )


def test_ticket_expiry_denied(phase4_app: Phase4App) -> None:
    call = ToolCall(
        id="exp",
        name="create_file",
        arguments={"root": "notes", "relative_path": "exp.md", "content": "x"},
    )
    outcome = phase4_app.chat.execute_tool_call(call, ctx=_ctx(phase4_app))
    verdict = outcome.pending_approval
    assert verdict is not None
    ticket = phase4_app.runtime.approval_store.grant(
        verdict,
        ctx=_ctx(phase4_app),
        method="user_text",
    )
    expired = NOW + timedelta(seconds=phase4_app.runtime.approval_store.ticket_ttl_s + 5)
    with pytest.raises(ApprovalMismatch):
        phase4_app.runtime.approval_store.consume(
            ticket.id,
            tool_name=call.name,
            args_hash=verdict.args_hash,
            now=expired,
        )


def test_typed_confirmation_cannot_use_plain_text_grant(phase4_app: Phase4App) -> None:
    target = phase4_app.data_root / "docs" / "notes" / "overwrite.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("old", encoding="utf-8")
    call = ToolCall(
        id="typed",
        name="create_file",
        arguments={
            "root": "notes",
            "relative_path": "overwrite.md",
            "content": "new",
            "overwrite": True,
        },
    )
    context = _ctx(phase4_app)
    outcome = phase4_app.chat.execute_tool_call(call, ctx=context)
    verdict = outcome.pending_approval
    assert verdict is not None
    assert verdict.decision == "typed_confirm"

    with pytest.raises(ApprovalMismatch):
        phase4_app.runtime.approval_store.grant(
            verdict,
            ctx=context,
            method="user_text",
        )

    ticket = phase4_app.runtime.approval_store.grant(
        verdict,
        ctx=context,
        method="user_typed_phrase",
    )
    assert ticket.granted_by == "user_typed_phrase"


def _ctx(phase4_app: Phase4App):
    chat = phase4_app.chat
    chat.start()
    request_id = phase4_app.runtime.ids.new("req")
    turn_id = phase4_app.runtime.ids.new("turn")
    from app.core.context import CancellationToken, RequestContext
    from app.orchestrator.loop import BoundEventWriter
    from app.telemetry.events import EventIdentity

    identity = EventIdentity(
        request_id=request_id,
        session_id=chat.session_id or phase4_app.runtime.ids.new("ses"),
        turn_id=turn_id,
    )
    return RequestContext(
        request_id=request_id,
        session_id=identity.session_id,
        turn_id=turn_id,
        task_id=None,
        started_at=NOW,
        clock=phase4_app.runtime.clock,
        sleeper=phase4_app.runtime.sleeper,
        random=phase4_app.runtime.random,
        settings=phase4_app.runtime.config.settings,
        events=BoundEventWriter(phase4_app.runtime.events, identity),
        audit=phase4_app.runtime.audit_writer,
        cancel=CancellationToken(),
        interactive=True,
        channel="text",
    )

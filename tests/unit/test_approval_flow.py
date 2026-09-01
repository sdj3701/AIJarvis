"""Unit tests for Phase 4 ApprovalStore and approval ticket flow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.core.context import RequestContext
from app.core.errors import ApprovalMismatch
from app.core.ids import SystemIdFactory
from app.safety.approval import InMemoryApprovalStore
from app.safety.gate import Verdict

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=KST)


@pytest.fixture
def approval_store() -> InMemoryApprovalStore:
    return InMemoryApprovalStore(
        ids=SystemIdFactory(),
        ticket_ttl_s=120,
        voice_max_risk="medium",
    )


def test_grant_medium_risk_approval(approval_store: InMemoryApprovalStore) -> None:
    verdict = Verdict(
        decision="confirm",
        risk="medium",
        reason="확인이 필요합니다.",
        tool_name="create_file",
        normalized_args={"root": "notes", "path": "memo.txt"},
        args_hash="hash_12345",
        display="새 파일 생성",
        capabilities=frozenset(["fs_write"]),
    )
    ctx = MagicMock(spec=RequestContext)
    ctx.request_id = "req_1"
    ctx.channel = "text"
    ctx.clock.now.return_value = NOW

    ticket = approval_store.grant(verdict, ctx=ctx, method="user_text")
    assert ticket.tool_name == "create_file"
    assert ticket.args_hash == "hash_12345"
    assert ticket.risk == "medium"
    assert ticket.granted_by == "user_text"
    assert ticket.expires_at == NOW + timedelta(seconds=120)


def test_grant_high_risk_requires_typed_phrase(approval_store: InMemoryApprovalStore) -> None:
    verdict = Verdict(
        decision="typed_confirm",
        risk="high",
        reason="덮어쓰기 확인이 필요합니다.",
        tool_name="create_file",
        normalized_args={"overwrite": True},
        args_hash="hash_overwrite",
        display="덮어쓰기",
        capabilities=frozenset(["fs_write"]),
    )
    ctx = MagicMock(spec=RequestContext)
    ctx.request_id = "req_1"
    ctx.channel = "text"
    ctx.clock.now.return_value = NOW

    # Reject plain user_text grant for high risk
    with pytest.raises(ApprovalMismatch, match="확인 문구를 직접 입력"):
        approval_store.grant(verdict, ctx=ctx, method="user_text")

    # Success with user_typed_phrase
    ticket = approval_store.grant(verdict, ctx=ctx, method="user_typed_phrase")
    assert ticket.granted_by == "user_typed_phrase"


def test_voice_channel_cannot_grant_high_risk(approval_store: InMemoryApprovalStore) -> None:
    verdict = Verdict(
        decision="typed_confirm",
        risk="high",
        reason="높은 위험",
        tool_name="create_file",
        normalized_args={},
        args_hash="hash_voice",
        display="위험",
        capabilities=frozenset(["fs_write"]),
    )
    ctx = MagicMock(spec=RequestContext)
    ctx.channel = "voice"
    ctx.clock.now.return_value = NOW

    with pytest.raises(ApprovalMismatch, match="음성 채널에서는 high 위험 작업을 승인할 수 없습니다"):
        approval_store.grant(verdict, ctx=ctx, method="user_typed_phrase")


def test_consume_ticket_validates_hash_and_single_use(approval_store: InMemoryApprovalStore) -> None:
    verdict = Verdict(
        decision="confirm",
        risk="medium",
        reason="확인",
        tool_name="close_app",
        normalized_args={"app": "notepad"},
        args_hash="hash_notepad",
        display="앱 종료",
        capabilities=frozenset(["proc_spawn"]),
    )
    ctx = MagicMock(spec=RequestContext)
    ctx.request_id = "req_2"
    ctx.channel = "text"
    ctx.clock.now.return_value = NOW

    ticket = approval_store.grant(verdict, ctx=ctx, method="user_text")

    # 1. Hash mismatch -> consume fails
    with pytest.raises(ApprovalMismatch, match="인자 해시가 일치하지 않습니다"):
        approval_store.consume(
            ticket.id,
            tool_name="close_app",
            args_hash="tampered_hash",
            now=NOW,
        )

    # 2. Valid consume -> success
    consumed = approval_store.consume(
        ticket.id,
        tool_name="close_app",
        args_hash="hash_notepad",
        now=NOW + timedelta(seconds=10),
    )
    assert consumed.id == ticket.id

    # 3. Reuse -> fails
    with pytest.raises(ApprovalMismatch, match="이미 사용된 승인 ticket"):
        approval_store.consume(
            ticket.id,
            tool_name="close_app",
            args_hash="hash_notepad",
            now=NOW + timedelta(seconds=20),
        )


def test_consume_ticket_expiry(approval_store: InMemoryApprovalStore) -> None:
    verdict = Verdict(
        decision="confirm",
        risk="medium",
        reason="확인",
        tool_name="open_folder",
        normalized_args={"root": "notes"},
        args_hash="hash_folder",
        display="폴더 열기",
        capabilities=frozenset(["fs_read"]),
    )
    ctx = MagicMock(spec=RequestContext)
    ctx.request_id = "req_3"
    ctx.channel = "text"
    ctx.clock.now.return_value = NOW

    ticket = approval_store.grant(verdict, ctx=ctx, method="user_text")

    # After 121 seconds (expired)
    expired_time = NOW + timedelta(seconds=121)
    with pytest.raises(ApprovalMismatch, match="만료되었습니다"):
        approval_store.consume(
            ticket.id,
            tool_name="open_folder",
            args_hash="hash_folder",
            now=expired_time,
        )

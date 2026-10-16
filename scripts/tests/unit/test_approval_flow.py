# 파이썬 공부 | scripts/tests/unit/test_approval_flow.py
# approval_flow 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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

# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9))
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=KST)


# approval_store(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: InMemoryApprovalStore.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def approval_store() -> InMemoryApprovalStore:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return InMemoryApprovalStore(
        ids=SystemIdFactory(),
        ticket_ttl_s=120,
        voice_max_risk="medium",
    )


# pytest가 test_grant_medium_risk_approval()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: approval_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_grant_medium_risk_approval(approval_store: InMemoryApprovalStore) -> None:
    # Verdict()의 반환값을 verdict에 대입합니다.
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
    # MagicMock()의 반환값을 ctx에 대입합니다.
    ctx = MagicMock(spec=RequestContext)
    # ctx.request_id에 문자열을 대입합니다.
    ctx.request_id = "req_1"
    # ctx.channel에 문자열을 대입합니다.
    ctx.channel = "text"
    # 오른쪽 식을 계산한 값을 ctx.clock.now.return_value에 대입합니다.
    ctx.clock.now.return_value = NOW

    # approval_store.grant()의 반환값을 ticket에 대입합니다.
    ticket = approval_store.grant(verdict, ctx=ctx, method="user_text")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ticket.tool_name == "create_file"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ticket.args_hash == "hash_12345"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ticket.risk == "medium"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ticket.granted_by == "user_text"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ticket.expires_at == NOW + timedelta(seconds=120)


# pytest가 test_grant_high_risk_requires_typed_phrase()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: approval_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_grant_high_risk_requires_typed_phrase(approval_store: InMemoryApprovalStore) -> None:
    # Verdict()의 반환값을 verdict에 대입합니다.
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
    # MagicMock()의 반환값을 ctx에 대입합니다.
    ctx = MagicMock(spec=RequestContext)
    # ctx.request_id에 문자열을 대입합니다.
    ctx.request_id = "req_1"
    # ctx.channel에 문자열을 대입합니다.
    ctx.channel = "text"
    # 오른쪽 식을 계산한 값을 ctx.clock.now.return_value에 대입합니다.
    ctx.clock.now.return_value = NOW

    # Reject plain user_text grant for high risk
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ApprovalMismatch, match="확인 문구를 직접 입력"):
        # approval_store.grant()을 호출해 작업을 수행합니다.
        approval_store.grant(verdict, ctx=ctx, method="user_text")

    # Success with user_typed_phrase
    # approval_store.grant()의 반환값을 ticket에 대입합니다.
    ticket = approval_store.grant(verdict, ctx=ctx, method="user_typed_phrase")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ticket.granted_by == "user_typed_phrase"


# pytest가 test_voice_channel_cannot_grant_high_risk()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: approval_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_voice_channel_cannot_grant_high_risk(approval_store: InMemoryApprovalStore) -> None:
    # Verdict()의 반환값을 verdict에 대입합니다.
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
    # MagicMock()의 반환값을 ctx에 대입합니다.
    ctx = MagicMock(spec=RequestContext)
    # ctx.channel에 문자열을 대입합니다.
    ctx.channel = "voice"
    # 오른쪽 식을 계산한 값을 ctx.clock.now.return_value에 대입합니다.
    ctx.clock.now.return_value = NOW

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ApprovalMismatch, match="음성 채널에서는 high 위험 작업을 승인할 수 없습니다"):
        # approval_store.grant()을 호출해 작업을 수행합니다.
        approval_store.grant(verdict, ctx=ctx, method="user_typed_phrase")


# pytest가 test_consume_ticket_validates_hash_and_single_use()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: approval_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_consume_ticket_validates_hash_and_single_use(approval_store: InMemoryApprovalStore) -> None:
    # Verdict()의 반환값을 verdict에 대입합니다.
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
    # MagicMock()의 반환값을 ctx에 대입합니다.
    ctx = MagicMock(spec=RequestContext)
    # ctx.request_id에 문자열을 대입합니다.
    ctx.request_id = "req_2"
    # ctx.channel에 문자열을 대입합니다.
    ctx.channel = "text"
    # 오른쪽 식을 계산한 값을 ctx.clock.now.return_value에 대입합니다.
    ctx.clock.now.return_value = NOW

    # approval_store.grant()의 반환값을 ticket에 대입합니다.
    ticket = approval_store.grant(verdict, ctx=ctx, method="user_text")

    # 1. Hash mismatch -> consume fails
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ApprovalMismatch, match="인자 해시가 일치하지 않습니다"):
        # approval_store.consume()을 호출해 작업을 수행합니다.
        approval_store.consume(
            ticket.id,
            tool_name="close_app",
            args_hash="tampered_hash",
            now=NOW,
        )

    # 2. Valid consume -> success
    # approval_store.consume()의 반환값을 consumed에 대입합니다.
    consumed = approval_store.consume(
        ticket.id,
        tool_name="close_app",
        args_hash="hash_notepad",
        now=NOW + timedelta(seconds=10),
    )
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert consumed.id == ticket.id

    # 3. Reuse -> fails
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ApprovalMismatch, match="이미 사용된 승인 ticket"):
        # approval_store.consume()을 호출해 작업을 수행합니다.
        approval_store.consume(
            ticket.id,
            tool_name="close_app",
            args_hash="hash_notepad",
            now=NOW + timedelta(seconds=20),
        )


# pytest가 test_consume_ticket_expiry()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: approval_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_consume_ticket_expiry(approval_store: InMemoryApprovalStore) -> None:
    # Verdict()의 반환값을 verdict에 대입합니다.
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
    # MagicMock()의 반환값을 ctx에 대입합니다.
    ctx = MagicMock(spec=RequestContext)
    # ctx.request_id에 문자열을 대입합니다.
    ctx.request_id = "req_3"
    # ctx.channel에 문자열을 대입합니다.
    ctx.channel = "text"
    # 오른쪽 식을 계산한 값을 ctx.clock.now.return_value에 대입합니다.
    ctx.clock.now.return_value = NOW

    # approval_store.grant()의 반환값을 ticket에 대입합니다.
    ticket = approval_store.grant(verdict, ctx=ctx, method="user_text")

    # After 121 seconds (expired)
    # 오른쪽 식을 계산한 값을 expired_time에 대입합니다.
    expired_time = NOW + timedelta(seconds=121)
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ApprovalMismatch, match="만료되었습니다"):
        # approval_store.consume()을 호출해 작업을 수행합니다.
        approval_store.consume(
            ticket.id,
            tool_name="open_folder",
            args_hash="hash_folder",
            now=expired_time,
        )

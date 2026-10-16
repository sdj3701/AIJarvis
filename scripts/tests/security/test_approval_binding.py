# 파이썬 공부 | scripts/tests/security/test_approval_binding.py
# approval_binding 관련 보안 경계을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Approval ticket binding and reuse rules."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.errors import ApprovalMismatch
from app.llm.base import ToolCall
from tests.helpers.phase4_app import NOW, Phase4App

# pytestmark에 리스트(순서가 있고 수정 가능)을 대입합니다.
pytestmark = [pytest.mark.phase4, pytest.mark.security]


# pytest가 test_args_change_invalidates_ticket()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_args_change_invalidates_ticket(phase4_app: Phase4App) -> None:
    # 오른쪽 식을 계산한 값을 chat에 대입합니다.
    chat = phase4_app.chat
    # _ctx()의 반환값을 context에 대입합니다.
    context = _ctx(phase4_app)
    # ToolCall()의 반환값을 call에 대입합니다.
    call = ToolCall(
        id="t1",
        name="create_file",
        arguments={
            "root": "notes",
            "relative_path": "a.md",
            "content": "hello",
        },
    )
    # chat.execute_tool_call()의 반환값을 outcome에 대입합니다.
    outcome = chat.execute_tool_call(call, ctx=context)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.pending_approval is not None
    # 오른쪽 식을 계산한 값을 verdict에 대입합니다.
    verdict = outcome.pending_approval
    # phase4_app.runtime.approval_store.grant()의 반환값을 ticket에 대입합니다.
    ticket = phase4_app.runtime.approval_store.grant(
        verdict,
        ctx=context,
        method="user_text",
    )
    # ToolCall()의 반환값을 changed에 대입합니다.
    changed = ToolCall(
        id="t2",
        name="create_file",
        arguments={
            "root": "notes",
            "relative_path": "b.md",
            "content": "hello",
        },
    )
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ApprovalMismatch):
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        phase4_app.runtime.tool_runner.execute(
            changed,
            ctx=context,
            ticket=ticket,
        )


# pytest가 test_ticket_reuse_denied()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_ticket_reuse_denied(phase4_app: Phase4App) -> None:
    import uuid

    # 오른쪽 식을 계산한 값을 name에 대입합니다.
    # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
    name = f"once-{uuid.uuid4().hex[:8]}.md"
    # 오른쪽 식을 계산한 값을 notes에 대입합니다.
    notes = phase4_app.data_root / "docs" / "notes"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    notes.mkdir(parents=True, exist_ok=True)
    # ToolCall()의 반환값을 call에 대입합니다.
    call = ToolCall(
        id="reuse",
        name="create_file",
        arguments={"root": "notes", "relative_path": name, "content": "x"},
    )
    # phase4_app.chat.execute_tool_call()의 반환값을 outcome에 대입합니다.
    outcome = phase4_app.chat.execute_tool_call(call, ctx=_ctx(phase4_app))
    # 오른쪽 식을 계산한 값을 verdict에 대입합니다.
    verdict = outcome.pending_approval
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert verdict is not None
    # phase4_app.runtime.approval_store.grant()의 반환값을 ticket에 대입합니다.
    ticket = phase4_app.runtime.approval_store.grant(
        verdict,
        ctx=_ctx(phase4_app),
        method="user_text",
    )
    # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
    phase4_app.runtime.tool_runner.execute(call, ctx=_ctx(phase4_app), ticket=ticket)
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ApprovalMismatch):
        # phase4_app.runtime.approval_store.consume()을 호출해 작업을 수행합니다.
        phase4_app.runtime.approval_store.consume(
            ticket.id,
            tool_name=call.name,
            args_hash=verdict.args_hash,
            now=NOW,
        )


# pytest가 test_ticket_expiry_denied()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_ticket_expiry_denied(phase4_app: Phase4App) -> None:
    # ToolCall()의 반환값을 call에 대입합니다.
    call = ToolCall(
        id="exp",
        name="create_file",
        arguments={"root": "notes", "relative_path": "exp.md", "content": "x"},
    )
    # phase4_app.chat.execute_tool_call()의 반환값을 outcome에 대입합니다.
    outcome = phase4_app.chat.execute_tool_call(call, ctx=_ctx(phase4_app))
    # 오른쪽 식을 계산한 값을 verdict에 대입합니다.
    verdict = outcome.pending_approval
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert verdict is not None
    # phase4_app.runtime.approval_store.grant()의 반환값을 ticket에 대입합니다.
    ticket = phase4_app.runtime.approval_store.grant(
        verdict,
        ctx=_ctx(phase4_app),
        method="user_text",
    )
    # 오른쪽 식을 계산한 값을 expired에 대입합니다.
    expired = NOW + timedelta(seconds=phase4_app.runtime.approval_store.ticket_ttl_s + 5)
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ApprovalMismatch):
        # phase4_app.runtime.approval_store.consume()을 호출해 작업을 수행합니다.
        phase4_app.runtime.approval_store.consume(
            ticket.id,
            tool_name=call.name,
            args_hash=verdict.args_hash,
            now=expired,
        )


# pytest가 test_typed_confirmation_cannot_use_plain_text_grant()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_typed_confirmation_cannot_use_plain_text_grant(phase4_app: Phase4App) -> None:
    # 오른쪽 식을 계산한 값을 target에 대입합니다.
    target = phase4_app.data_root / "docs" / "notes" / "overwrite.md"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    target.parent.mkdir(parents=True, exist_ok=True)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    target.write_text("old", encoding="utf-8")
    # ToolCall()의 반환값을 call에 대입합니다.
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
    # _ctx()의 반환값을 context에 대입합니다.
    context = _ctx(phase4_app)
    # phase4_app.chat.execute_tool_call()의 반환값을 outcome에 대입합니다.
    outcome = phase4_app.chat.execute_tool_call(call, ctx=context)
    # 오른쪽 식을 계산한 값을 verdict에 대입합니다.
    verdict = outcome.pending_approval
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert verdict is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert verdict.decision == "typed_confirm"

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ApprovalMismatch):
        # phase4_app.runtime.approval_store.grant()을 호출해 작업을 수행합니다.
        phase4_app.runtime.approval_store.grant(
            verdict,
            ctx=context,
            method="user_text",
        )

    # phase4_app.runtime.approval_store.grant()의 반환값을 ticket에 대입합니다.
    ticket = phase4_app.runtime.approval_store.grant(
        verdict,
        ctx=context,
        method="user_typed_phrase",
    )
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ticket.granted_by == "user_typed_phrase"


# _ctx(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: phase4_app.
def _ctx(phase4_app: Phase4App):
    # 오른쪽 식을 계산한 값을 chat에 대입합니다.
    chat = phase4_app.chat
    # chat.start()을 호출해 작업을 수행합니다.
    chat.start()
    # phase4_app.runtime.ids.new()의 반환값을 request_id에 대입합니다.
    request_id = phase4_app.runtime.ids.new("req")
    # phase4_app.runtime.ids.new()의 반환값을 turn_id에 대입합니다.
    turn_id = phase4_app.runtime.ids.new("turn")
    from app.core.context import CancellationToken, RequestContext
    from app.orchestrator.loop import BoundEventWriter
    from app.telemetry.events import EventIdentity

    # EventIdentity()의 반환값을 identity에 대입합니다.
    identity = EventIdentity(
        request_id=request_id,
        session_id=chat.session_id or phase4_app.runtime.ids.new("ses"),
        turn_id=turn_id,
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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

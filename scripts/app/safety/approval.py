# 파이썬 공부 | scripts/app/safety/approval.py
# 한 번만 사용할 수 있는 실행 승인 정보를 프로세스 메모리에서 관리합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""In-memory approval ticket store (process-local, one-shot)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

from app.core.context import RequestContext
from app.core.errors import ApprovalMismatch
from app.core.ids import PrefixedIdFactory
from app.safety.gate import Verdict
from app.tools.base import Risk

# 오른쪽 식을 계산한 값을 GrantMethod에 대입합니다.
GrantMethod = Literal["user_text", "user_typed_phrase"]


# ApprovalTicket: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class ApprovalTicket:
    # id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    id: str
    # request_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    request_id: str
    # tool_name: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    tool_name: str
    # args_hash: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    args_hash: str
    # risk: Risk 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    risk: Risk
    # granted_at: datetime 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    granted_at: datetime
    # expires_at: datetime 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    expires_at: datetime
    # granted_by: GrantMethod 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    granted_by: GrantMethod
    # channel: Literal['text', 'voice'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    channel: Literal["text", "voice"]


# ApprovalStore: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class ApprovalStore(Protocol):
    # grant(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: verdict, ctx, method.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: ApprovalTicket.
    def grant(
        self,
        verdict: Verdict,
        *,
        ctx: RequestContext,
        method: GrantMethod,
    ) -> ApprovalTicket: ...

    # consume(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: ticket_id, tool_name, args_hash, now.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: ApprovalTicket.
    def consume(
        self,
        ticket_id: str,
        *,
        tool_name: str,
        args_hash: str,
        now: datetime,
    ) -> ApprovalTicket: ...

    # discard(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: ticket_id.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def discard(self, ticket_id: str) -> None: ...


# InMemoryApprovalStore: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class InMemoryApprovalStore:
    # ids: PrefixedIdFactory 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ids: PrefixedIdFactory
    # ticket_ttl_s: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ticket_ttl_s: int
    # voice_max_risk: Risk 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    voice_max_risk: Risk
    # _tickets: dict[str, ApprovalTicket] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    _tickets: dict[str, ApprovalTicket]
    # _consumed: set[str] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    _consumed: set[str]

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: ids, ticket_ttl_s, voice_max_risk.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        *,
        ids: PrefixedIdFactory,
        ticket_ttl_s: int,
        voice_max_risk: Risk,
    ) -> None:
        # 오른쪽 식을 계산한 값을 self.ids에 대입합니다.
        self.ids = ids
        # 오른쪽 식을 계산한 값을 self.ticket_ttl_s에 대입합니다.
        self.ticket_ttl_s = ticket_ttl_s
        # 오른쪽 식을 계산한 값을 self.voice_max_risk에 대입합니다.
        self.voice_max_risk = voice_max_risk
        # self._tickets에 딕셔너리(키와 값의 쌍)을 대입합니다.
        self._tickets = {}
        # set()의 반환값을 self._consumed에 대입합니다.
        self._consumed = set()

    # grant(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: verdict, ctx, method.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: ApprovalTicket.
    def grant(
        self,
        verdict: Verdict,
        *,
        ctx: RequestContext,
        method: GrantMethod,
    ) -> ApprovalTicket:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: verdict.decision not in {'confirm',
        # 'typed_confirm'}.
        if verdict.decision not in {"confirm", "typed_confirm"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ApprovalMismatch("승인이 필요하지 않은 판정에는 ticket을 발급할 수 없습니다.")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if verdict.decision == "typed_confirm" and method != "user_typed_phrase":
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ApprovalMismatch("높은 위험 작업은 확인 문구를 직접 입력해야 합니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ctx.channel == 'voice' and
        # verdict.risk == 'high'.
        if ctx.channel == "voice" and verdict.risk == "high":
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ApprovalMismatch("음성 채널에서는 high 위험 작업을 승인할 수 없습니다.")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if ctx.channel == "voice" and verdict.risk == "medium" and self.voice_max_risk == "low":
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ApprovalMismatch("음성 채널에서는 medium 이상 작업을 승인할 수 없습니다.")
        # ctx.clock.now()의 반환값을 now에 대입합니다.
        now = ctx.clock.now()
        # ApprovalTicket()의 반환값을 ticket에 대입합니다.
        ticket = ApprovalTicket(
            id=self.ids.new("apv"),
            request_id=ctx.request_id,
            tool_name=verdict.tool_name,
            args_hash=verdict.args_hash,
            risk=verdict.risk,
            granted_at=now,
            expires_at=now + timedelta(seconds=self.ticket_ttl_s),
            granted_by=method,
            channel=ctx.channel,
        )
        # 오른쪽 식을 계산한 값을 self._tickets[ticket.id]에 대입합니다.
        self._tickets[ticket.id] = ticket
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ticket

    # consume(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: ticket_id, tool_name, args_hash, now.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: ApprovalTicket.
    def consume(
        self,
        ticket_id: str,
        *,
        tool_name: str,
        args_hash: str,
        now: datetime,
    ) -> ApprovalTicket:
        # self._tickets.get()의 반환값을 ticket에 대입합니다.
        ticket = self._tickets.get(ticket_id)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ticket is None.
        if ticket is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ApprovalMismatch("승인 ticket이 없습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ticket_id in self._consumed.
        if ticket_id in self._consumed:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ApprovalMismatch("이미 사용된 승인 ticket입니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: now >= ticket.expires_at.
        if now >= ticket.expires_at:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ApprovalMismatch("승인 ticket이 만료되었습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ticket.tool_name != tool_name.
        if ticket.tool_name != tool_name:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ApprovalMismatch("승인 ticket의 도구명이 일치하지 않습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ticket.args_hash != args_hash.
        if ticket.args_hash != args_hash:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ApprovalMismatch("승인 ticket의 인자 해시가 일치하지 않습니다.")
        # add 메서드를 호출해 항목이나 기록을 추가합니다.
        self._consumed.add(ticket_id)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ticket

    # discard(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: ticket_id.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def discard(self, ticket_id: str) -> None:
        # self._tickets.pop()을 호출해 작업을 수행합니다.
        self._tickets.pop(ticket_id, None)
        # add 메서드를 호출해 항목이나 기록을 추가합니다.
        self._consumed.add(ticket_id)

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

GrantMethod = Literal["user_text", "user_typed_phrase"]


@dataclass(frozen=True, slots=True)
class ApprovalTicket:
    id: str
    request_id: str
    tool_name: str
    args_hash: str
    risk: Risk
    granted_at: datetime
    expires_at: datetime
    granted_by: GrantMethod
    channel: Literal["text", "voice"]


class ApprovalStore(Protocol):
    def grant(
        self,
        verdict: Verdict,
        *,
        ctx: RequestContext,
        method: GrantMethod,
    ) -> ApprovalTicket: ...

    def consume(
        self,
        ticket_id: str,
        *,
        tool_name: str,
        args_hash: str,
        now: datetime,
    ) -> ApprovalTicket: ...

    def discard(self, ticket_id: str) -> None: ...


@dataclass
class InMemoryApprovalStore:
    ids: PrefixedIdFactory
    ticket_ttl_s: int
    voice_max_risk: Risk
    _tickets: dict[str, ApprovalTicket]
    _consumed: set[str]

    def __init__(
        self,
        *,
        ids: PrefixedIdFactory,
        ticket_ttl_s: int,
        voice_max_risk: Risk,
    ) -> None:
        self.ids = ids
        self.ticket_ttl_s = ticket_ttl_s
        self.voice_max_risk = voice_max_risk
        self._tickets = {}
        self._consumed = set()

    def grant(
        self,
        verdict: Verdict,
        *,
        ctx: RequestContext,
        method: GrantMethod,
    ) -> ApprovalTicket:
        if verdict.decision not in {"confirm", "typed_confirm"}:
            raise ApprovalMismatch("승인이 필요하지 않은 판정에는 ticket을 발급할 수 없습니다.")
        if verdict.decision == "typed_confirm" and method != "user_typed_phrase":
            raise ApprovalMismatch("높은 위험 작업은 확인 문구를 직접 입력해야 합니다.")
        if ctx.channel == "voice" and verdict.risk == "high":
            raise ApprovalMismatch("음성 채널에서는 high 위험 작업을 승인할 수 없습니다.")
        if ctx.channel == "voice" and verdict.risk == "medium" and self.voice_max_risk == "low":
            raise ApprovalMismatch("음성 채널에서는 medium 이상 작업을 승인할 수 없습니다.")
        now = ctx.clock.now()
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
        self._tickets[ticket.id] = ticket
        return ticket

    def consume(
        self,
        ticket_id: str,
        *,
        tool_name: str,
        args_hash: str,
        now: datetime,
    ) -> ApprovalTicket:
        ticket = self._tickets.get(ticket_id)
        if ticket is None:
            raise ApprovalMismatch("승인 ticket이 없습니다.")
        if ticket_id in self._consumed:
            raise ApprovalMismatch("이미 사용된 승인 ticket입니다.")
        if now >= ticket.expires_at:
            raise ApprovalMismatch("승인 ticket이 만료되었습니다.")
        if ticket.tool_name != tool_name:
            raise ApprovalMismatch("승인 ticket의 도구명이 일치하지 않습니다.")
        if ticket.args_hash != args_hash:
            raise ApprovalMismatch("승인 ticket의 인자 해시가 일치하지 않습니다.")
        self._consumed.add(ticket_id)
        return ticket

    def discard(self, ticket_id: str) -> None:
        self._tickets.pop(ticket_id, None)
        self._consumed.add(ticket_id)

"""Per-request dependencies and cooperative cancellation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from threading import Event
from typing import TYPE_CHECKING, Any, Literal, Protocol

from app.core.clock import Clock, RandomSource, Sleeper

if TYPE_CHECKING:
    from app.config.models import Settings

_ULID_PATTERN = r"[0-9A-HJKMNP-TV-Z]{26}"


class EventWriter(Protocol):
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


class AuditWriter(Protocol):
    def write(self, record: Mapping[str, Any]) -> None: ...


class CancelToken(Protocol):
    def cancelled(self) -> bool: ...

    def raise_if_cancelled(self) -> None: ...


class CancellationToken:
    """Thread-safe cooperative cancellation token."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled():
            raise InterruptedError("작업이 취소되었습니다.")


@dataclass(frozen=True, slots=True)
class RequestContext:
    request_id: str
    session_id: str
    turn_id: str
    task_id: str | None
    started_at: datetime
    clock: Clock
    sleeper: Sleeper
    random: RandomSource
    settings: Settings  # injected; config is imported only under TYPE_CHECKING
    events: EventWriter
    audit: AuditWriter
    cancel: CancelToken
    interactive: bool
    channel: Literal["text", "voice"]
    memory_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("RequestContext.started_at must be timezone-aware")
        _validate_id(self.request_id, "req")
        _validate_id(self.session_id, "ses")
        _validate_id(self.turn_id, "turn")
        if self.task_id is not None:
            _validate_id(self.task_id, "task")
        if self.channel not in {"text", "voice"}:
            raise ValueError("RequestContext.channel must be text or voice")


def _validate_id(value: str, prefix: str) -> None:
    if not re.fullmatch(rf"{prefix}_{_ULID_PATTERN}", value):
        raise ValueError(f"invalid {prefix} identifier")

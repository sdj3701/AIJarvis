"""Explicit memory commands for Phase 2 CLI."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from app.core.clock import Clock
from app.core.errors import MemoryError as JarvisMemoryError
from app.core.ids import PrefixedIdFactory
from app.memory.models import (
    MemoryRecord,
    RecordKind,
    RecordStatus,
    new_fact_id,
    validate_memory_key,
)
from app.memory.retrieval import extract_key_candidates
from app.memory.store import SQLiteSessionStore

_REMEMBER_PREFIX = re.compile(r"^기억해\s*:?\s*", re.IGNORECASE)
_CORRECTION = re.compile(
    r"^틀림\s*:\s*(?P<old>.+?)\s*(?:→|->)\s*(?P<new>.+)\s*$",
    re.IGNORECASE,
)
_MEMORY_LIST = re.compile(
    r"^/memory\s+list(?:\s+(?P<status>candidate|confirmed|superseded|deleted))?"
    r"(?:\s+(?P<kind>fact|correction|summary|doc_chunk))?\s*$",
    re.IGNORECASE,
)
_MEMORY_CONFIRM = re.compile(r"^/memory\s+confirm\s+(?P<id>\S+)\s*$", re.IGNORECASE)
_MEMORY_EDIT = re.compile(r"^/memory\s+edit\s+(?P<id>\S+)\s+(?P<value>.+)\s*$", re.IGNORECASE)
_FORGET = re.compile(r"^/forget\s+(?P<id>\S+)\s*$", re.IGNORECASE)
_MEMORY_EXPORT = re.compile(r"^/memory\s+export\s*$", re.IGNORECASE)


class EventSink(Protocol):
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class CommandResult:
    ok: bool
    message: str
    record_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryCommandContext:
    store: SQLiteSessionStore
    ids: PrefixedIdFactory
    clock: Clock
    session_id: str
    key_aliases: Mapping[str, Sequence[str]]
    export_dir: Path | None = None
    turn_id: str | None = None
    events: EventSink | None = None


def _now(clock: Clock) -> datetime:
    return clock.now()


def _emit(events: EventSink | None, event_type: str, payload: Mapping[str, Any]) -> None:
    if events is not None:
        events.emit(event_type, payload)


def _emit_write(
    events: EventSink | None,
    *,
    record_id: str,
    kind: RecordKind,
    status: RecordStatus,
    source_kind: Literal["user_explicit", "summarizer", "import"],
) -> None:
    _emit(
        events,
        "memory.write",
        {
            "record_id": record_id,
            "kind": kind,
            "status": status,
            "source_kind": source_kind,
        },
    )


def _find_confirmed_by_value_or_key(
    store: SQLiteSessionStore,
    needle: str,
) -> MemoryRecord | None:
    needle_cf = needle.casefold().strip()
    for record in store.list_records(status="confirmed", limit=500):
        if record.key is not None and record.key.casefold() == needle_cf:
            return record
        if record.value.casefold() == needle_cf:
            return record
    return None


def _remember(text: str, ctx: MemoryCommandContext) -> CommandResult:
    body = _REMEMBER_PREFIX.sub("", text.strip(), count=1).strip()
    if not body:
        return CommandResult(False, "기억할 내용을 입력해 주세요. 예: 기억해: 말투는 짧게")

    keys = extract_key_candidates(body, ctx.key_aliases)
    if len(keys) == 0:
        return CommandResult(
            False,
            "어떤 종류의 기억인지 key를 찾지 못했습니다. "
            "예: 기억해: 말투는 짧고 근거 포함 (별칭: 말투, 답변 스타일 등)",
        )
    if len(keys) > 1:
        joined = ", ".join(keys)
        return CommandResult(
            False,
            f"여러 key 후보가 겹칩니다 ({joined}). 하나만 명확히 적어 주세요.",
        )

    key = keys[0]
    value = body
    for alias in ctx.key_aliases.get(key, ()):
        value = re.sub(re.escape(alias), "", value, flags=re.IGNORECASE).strip(" :은는이가을를")
    if not value.strip():
        value = body

    now = _now(ctx.clock)
    record = MemoryRecord(
        id=new_fact_id(),
        schema_version=1,
        kind="fact",
        key=key,
        value=value.strip(),
        status="confirmed",
        source_session_id=ctx.session_id,
        source_turn_id=ctx.turn_id,
        source_kind="user_explicit",
        created_at=now,
        updated_at=now,
        expires_at=None,
        sensitivity="normal",
        supersedes=None,
        tags=("user_explicit",),
    )
    try:
        ctx.store.put_record(record)
    except JarvisMemoryError as error:
        return CommandResult(False, error.user_message)

    _emit_write(
        ctx.events,
        record_id=record.id,
        kind="fact",
        status="confirmed",
        source_kind="user_explicit",
    )
    return CommandResult(
        True,
        f"기억했습니다. [{key}] {record.value}",
        (record.id,),
    )


def _correct(text: str, ctx: MemoryCommandContext) -> CommandResult:
    match = _CORRECTION.match(text.strip())
    if match is None:
        return CommandResult(False, "틀림 명령 형식: 틀림: 이전값 → 새값")

    old_text = match.group("old").strip()
    new_text = match.group("new").strip()
    if not old_text or not new_text:
        return CommandResult(False, "틀림 명령에 이전값과 새값이 모두 필요합니다.")

    target = _find_confirmed_by_value_or_key(ctx.store, old_text)
    if target is None or target.key is None:
        return CommandResult(
            False,
            f"확정된 기억 '{old_text}'(또는 key)을 찾지 못했습니다.",
        )

    now = _now(ctx.clock)
    new_record = MemoryRecord(
        id=new_fact_id(),
        schema_version=1,
        kind="correction",
        key=target.key,
        value=new_text,
        status="confirmed",
        source_session_id=ctx.session_id,
        source_turn_id=ctx.turn_id,
        source_kind="user_explicit",
        created_at=now,
        updated_at=now,
        expires_at=None,
        sensitivity=target.sensitivity,
        supersedes=target.id,
        tags=("correction",),
    )
    try:
        ctx.store.put_record(new_record)
        ctx.store.supersede(target.id, new_record.id, now)
    except JarvisMemoryError as error:
        return CommandResult(False, error.user_message)

    _emit_write(
        ctx.events,
        record_id=new_record.id,
        kind="correction",
        status="confirmed",
        source_kind="user_explicit",
    )
    _emit(
        ctx.events,
        "memory.supersede",
        {"old_id": target.id, "new_id": new_record.id, "key": target.key},
    )
    return CommandResult(
        True,
        f"교정했습니다. [{target.key}] {old_text} → {new_text}",
        (new_record.id,),
    )


def _list_records(text: str, ctx: MemoryCommandContext) -> CommandResult:
    match = _MEMORY_LIST.match(text.strip())
    if match is None:
        return CommandResult(False, "목록 형식: /memory list [status] [kind]")

    status_raw = match.group("status")
    kind_raw = match.group("kind")
    status: RecordStatus | None = status_raw.lower() if status_raw else None  # type: ignore[assignment]
    kind: RecordKind | None = kind_raw.lower() if kind_raw else None  # type: ignore[assignment]

    records = ctx.store.list_records(status=status, kind=kind, limit=20)
    if not records:
        return CommandResult(True, "표시할 기억이 없습니다.")

    lines = ["저장된 기억 (최근 20건):"]
    for record in records:
        key_part = f"[{record.key}] " if record.key else ""
        lines.append(f"- {record.id} {record.kind}/{record.status} {key_part}{record.value}")
    return CommandResult(True, "\n".join(lines))


def _confirm(text: str, ctx: MemoryCommandContext) -> CommandResult:
    match = _MEMORY_CONFIRM.match(text.strip())
    if match is None:
        return CommandResult(False, "형식: /memory confirm <id>")

    record_id = match.group("id")
    try:
        confirmed = ctx.store.confirm(record_id, _now(ctx.clock))
    except JarvisMemoryError as error:
        return CommandResult(False, error.user_message)

    _emit(ctx.events, "memory.confirm", {"record_id": record_id, "key": confirmed.key})
    return CommandResult(True, f"확정했습니다. {record_id}", (record_id,))


def _edit(text: str, ctx: MemoryCommandContext) -> CommandResult:
    match = _MEMORY_EDIT.match(text.strip())
    if match is None:
        return CommandResult(False, "형식: /memory edit <id> <새 값>")

    record_id = match.group("id")
    new_value = match.group("value").strip()
    existing = ctx.store.get_record(record_id)
    if existing is None:
        return CommandResult(False, f"기억 {record_id}을 찾지 못했습니다.")
    if existing.status not in {"confirmed", "candidate"}:
        return CommandResult(False, "확정·후보만 수정할 수 있습니다.")
    if existing.key is None or not validate_memory_key(existing.key):
        return CommandResult(False, "key가 없는 레코드는 수정할 수 없습니다.")

    now = _now(ctx.clock)
    kind: RecordKind = "correction" if existing.status == "confirmed" else "fact"
    new_record = MemoryRecord(
        id=new_fact_id(),
        schema_version=1,
        kind=kind,
        key=existing.key,
        value=new_value,
        status="confirmed",
        source_session_id=ctx.session_id,
        source_turn_id=ctx.turn_id,
        source_kind="user_explicit",
        created_at=now,
        updated_at=now,
        expires_at=None,
        sensitivity=existing.sensitivity,
        supersedes=existing.id,
        tags=("edit",),
    )
    try:
        ctx.store.put_record(new_record)
        if existing.status == "confirmed":
            ctx.store.supersede(existing.id, new_record.id, now)
        else:
            ctx.store.soft_delete(existing.id, "edited", now)
    except JarvisMemoryError as error:
        return CommandResult(False, error.user_message)

    _emit_write(
        ctx.events,
        record_id=new_record.id,
        kind=kind,
        status="confirmed",
        source_kind="user_explicit",
    )
    if existing.status == "confirmed":
        _emit(
            ctx.events,
            "memory.supersede",
            {"old_id": existing.id, "new_id": new_record.id, "key": existing.key},
        )
    return CommandResult(True, f"수정했습니다. [{existing.key}] {new_value}", (new_record.id,))


def _forget(text: str, ctx: MemoryCommandContext) -> CommandResult:
    match = _FORGET.match(text.strip())
    if match is None:
        return CommandResult(False, "형식: /forget <id>")

    record_id = match.group("id")
    try:
        ctx.store.soft_delete(record_id, "user_forget", _now(ctx.clock))
    except JarvisMemoryError as error:
        return CommandResult(False, error.user_message)

    _emit(ctx.events, "memory.delete", {"record_id": record_id, "reason": "user_forget"})
    return CommandResult(True, f"삭제했습니다. {record_id}", (record_id,))


def _export(ctx: MemoryCommandContext) -> CommandResult:
    if ctx.export_dir is None:
        return CommandResult(False, "내보내기 경로가 설정되지 않았습니다.")
    export_file = ctx.store.export(ctx.export_dir, include_raw=False)
    return CommandResult(True, f"내보냈습니다. {export_file}")


def try_handle_memory_command(text: str, ctx: MemoryCommandContext) -> CommandResult | None:
    """Parse and execute memory commands; return None if the line is not a memory command."""
    stripped = text.strip()
    if not stripped:
        return None

    if _REMEMBER_PREFIX.match(stripped):
        return _remember(stripped, ctx)
    if _CORRECTION.match(stripped):
        return _correct(stripped, ctx)
    if _MEMORY_LIST.match(stripped):
        return _list_records(stripped, ctx)
    if _MEMORY_CONFIRM.match(stripped):
        return _confirm(stripped, ctx)
    if _MEMORY_EDIT.match(stripped):
        return _edit(stripped, ctx)
    if _FORGET.match(stripped):
        return _forget(stripped, ctx)
    if _MEMORY_EXPORT.match(stripped):
        return _export(ctx)
    return None

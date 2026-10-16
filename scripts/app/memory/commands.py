# 파이썬 공부 | scripts/app/memory/commands.py
# 기억 조회·저장 등 사용자가 명시적으로 입력한 명령을 처리합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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

# re.compile()의 반환값을 _REMEMBER_PREFIX에 대입합니다.
_REMEMBER_PREFIX = re.compile(r"^기억해\s*:?\s*", re.IGNORECASE)
# re.compile()의 반환값을 _CORRECTION에 대입합니다.
_CORRECTION = re.compile(
    r"^틀림\s*:\s*(?P<old>.+?)\s*(?:→|->)\s*(?P<new>.+)\s*$",
    re.IGNORECASE,
)
# re.compile()의 반환값을 _MEMORY_LIST에 대입합니다.
_MEMORY_LIST = re.compile(
    r"^/memory\s+list(?:\s+(?P<status>candidate|confirmed|superseded|deleted))?"
    r"(?:\s+(?P<kind>fact|correction|summary|doc_chunk))?\s*$",
    re.IGNORECASE,
)
# re.compile()의 반환값을 _MEMORY_CONFIRM에 대입합니다.
_MEMORY_CONFIRM = re.compile(r"^/memory\s+confirm\s+(?P<id>\S+)\s*$", re.IGNORECASE)
# re.compile()의 반환값을 _MEMORY_EDIT에 대입합니다.
_MEMORY_EDIT = re.compile(r"^/memory\s+edit\s+(?P<id>\S+)\s+(?P<value>.+)\s*$", re.IGNORECASE)
# re.compile()의 반환값을 _FORGET에 대입합니다.
_FORGET = re.compile(r"^/forget\s+(?P<id>\S+)\s*$", re.IGNORECASE)
# re.compile()의 반환값을 _MEMORY_EXPORT에 대입합니다.
_MEMORY_EXPORT = re.compile(r"^/memory\s+export\s*$", re.IGNORECASE)


# EventSink: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class EventSink(Protocol):
    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


# CommandResult: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class CommandResult:
    # ok: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ok: bool
    # message: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    message: str
    # record_ids에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    record_ids: tuple[str, ...] = ()


# MemoryCommandContext: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class MemoryCommandContext:
    # store: SQLiteSessionStore 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    store: SQLiteSessionStore
    # ids: PrefixedIdFactory 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ids: PrefixedIdFactory
    # clock: Clock 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    clock: Clock
    # session_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    session_id: str
    # key_aliases: Mapping[str, Sequence[str]] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    key_aliases: Mapping[str, Sequence[str]]
    # export_dir을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    export_dir: Path | None = None
    # turn_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    turn_id: str | None = None
    # events을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    events: EventSink | None = None


# _now(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: clock.
# 반환 타입 힌트: datetime.
def _now(clock: Clock) -> datetime:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return clock.now()


# _emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: events, event_type, payload.
# 반환 타입 힌트: 별도 결과 없음(None).
def _emit(events: EventSink | None, event_type: str, payload: Mapping[str, Any]) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: events is not None.
    if events is not None:
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        events.emit(event_type, payload)


# _emit_write(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: events, record_id, kind, status, source_kind.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def _emit_write(
    events: EventSink | None,
    *,
    record_id: str,
    kind: RecordKind,
    status: RecordStatus,
    source_kind: Literal["user_explicit", "summarizer", "import"],
) -> None:
    # _emit()을 호출해 작업을 수행합니다.
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


# _find_confirmed_by_value_or_key(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: store, needle.
# 반환 타입 힌트: MemoryRecord | None.
def _find_confirmed_by_value_or_key(
    store: SQLiteSessionStore,
    needle: str,
) -> MemoryRecord | None:
    # needle.casefold().strip()의 반환값을 needle_cf에 대입합니다.
    needle_cf = needle.casefold().strip()
    # for 반복문: 대상의 항목을 하나씩 record에 대입하며 아래 블록을 실행합니다.
    for record in store.list_records(status="confirmed", limit=500):
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: record.key is not None and
        # record.key.casefold() ==
        # needle_cf.
        if record.key is not None and record.key.casefold() == needle_cf:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return record
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: record.value.casefold() == needle_cf.
        if record.value.casefold() == needle_cf:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return record
    # None을 반환하고 이 함수의 실행을 끝냅니다.
    return None


# _remember(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text, ctx.
# 반환 타입 힌트: CommandResult.
def _remember(text: str, ctx: MemoryCommandContext) -> CommandResult:
    # 아래 함수()의 반환값을 body에 대입합니다.
    body = _REMEMBER_PREFIX.sub("", text.strip(), count=1).strip()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not body.
    if not body:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, "기억할 내용을 입력해 주세요. 예: 기억해: 말투는 짧게")

    # extract_key_candidates()의 반환값을 keys에 대입합니다.
    keys = extract_key_candidates(body, ctx.key_aliases)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(keys) == 0.
    if len(keys) == 0:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(
            False,
            "어떤 종류의 기억인지 key를 찾지 못했습니다. "
            "예: 기억해: 말투는 짧고 근거 포함 (별칭: 말투, 답변 스타일 등)",
        )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(keys) > 1.
    if len(keys) > 1:
        # ', '.join()의 반환값을 joined에 대입합니다.
        joined = ", ".join(keys)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(
            False,
            f"여러 key 후보가 겹칩니다 ({joined}). 하나만 명확히 적어 주세요.",
        )

    # 오른쪽 식을 계산한 값을 key에 대입합니다.
    key = keys[0]
    # 오른쪽 식을 계산한 값을 value에 대입합니다.
    value = body
    # for 반복문: 대상의 항목을 하나씩 alias에 대입하며 아래 블록을 실행합니다.
    for alias in ctx.key_aliases.get(key, ()):
        # 아래 함수()의 반환값을 value에 대입합니다.
        value = re.sub(re.escape(alias), "", value, flags=re.IGNORECASE).strip(" :은는이가을를")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not value.strip().
    if not value.strip():
        # 오른쪽 식을 계산한 값을 value에 대입합니다.
        value = body

    # _now()의 반환값을 now에 대입합니다.
    now = _now(ctx.clock)
    # MemoryRecord()의 반환값을 record에 대입합니다.
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
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # ctx.store.put_record()을 호출해 작업을 수행합니다.
        ctx.store.put_record(record)
    # JarvisMemoryError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except JarvisMemoryError as error:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, error.user_message)

    # _emit_write()을 호출해 작업을 수행합니다.
    _emit_write(
        ctx.events,
        record_id=record.id,
        kind="fact",
        status="confirmed",
        source_kind="user_explicit",
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return CommandResult(
        True,
        f"기억했습니다. [{key}] {record.value}",
        (record.id,),
    )


# _correct(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text, ctx.
# 반환 타입 힌트: CommandResult.
def _correct(text: str, ctx: MemoryCommandContext) -> CommandResult:
    # _CORRECTION.match()의 반환값을 match에 대입합니다.
    match = _CORRECTION.match(text.strip())
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match is None.
    if match is None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, "틀림 명령 형식: 틀림: 이전값 → 새값")

    # match.group('old').strip()의 반환값을 old_text에 대입합니다.
    old_text = match.group("old").strip()
    # match.group('new').strip()의 반환값을 new_text에 대입합니다.
    new_text = match.group("new").strip()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not old_text or not new_text.
    if not old_text or not new_text:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, "틀림 명령에 이전값과 새값이 모두 필요합니다.")

    # _find_confirmed_by_value_or_key()의 반환값을 target에 대입합니다.
    target = _find_confirmed_by_value_or_key(ctx.store, old_text)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: target is None or target.key is None.
    if target is None or target.key is None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(
            False,
            f"확정된 기억 '{old_text}'(또는 key)을 찾지 못했습니다.",
        )

    # _now()의 반환값을 now에 대입합니다.
    now = _now(ctx.clock)
    # MemoryRecord()의 반환값을 new_record에 대입합니다.
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
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # ctx.store.put_record()을 호출해 작업을 수행합니다.
        ctx.store.put_record(new_record)
        # ctx.store.supersede()을 호출해 작업을 수행합니다.
        ctx.store.supersede(target.id, new_record.id, now)
    # JarvisMemoryError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except JarvisMemoryError as error:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, error.user_message)

    # _emit_write()을 호출해 작업을 수행합니다.
    _emit_write(
        ctx.events,
        record_id=new_record.id,
        kind="correction",
        status="confirmed",
        source_kind="user_explicit",
    )
    # _emit()을 호출해 작업을 수행합니다.
    _emit(
        ctx.events,
        "memory.supersede",
        {"old_id": target.id, "new_id": new_record.id, "key": target.key},
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return CommandResult(
        True,
        f"교정했습니다. [{target.key}] {old_text} → {new_text}",
        (new_record.id,),
    )


# _list_records(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text, ctx.
# 반환 타입 힌트: CommandResult.
def _list_records(text: str, ctx: MemoryCommandContext) -> CommandResult:
    # _MEMORY_LIST.match()의 반환값을 match에 대입합니다.
    match = _MEMORY_LIST.match(text.strip())
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match is None.
    if match is None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, "목록 형식: /memory list [status] [kind]")

    # match.group()의 반환값을 status_raw에 대입합니다.
    status_raw = match.group("status")
    # match.group()의 반환값을 kind_raw에 대입합니다.
    kind_raw = match.group("kind")
    # 오른쪽 식을 계산한 값을 status에 대입합니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    status: RecordStatus | None = status_raw.lower() if status_raw else None  # type: ignore[assignment]
    # 오른쪽 식을 계산한 값을 kind에 대입합니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    kind: RecordKind | None = kind_raw.lower() if kind_raw else None  # type: ignore[assignment]

    # ctx.store.list_records()의 반환값을 records에 대입합니다.
    records = ctx.store.list_records(status=status, kind=kind, limit=20)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not records.
    if not records:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(True, "표시할 기억이 없습니다.")

    # lines에 리스트(순서가 있고 수정 가능)을 대입합니다.
    lines = ["저장된 기억 (최근 20건):"]
    # for 반복문: 대상의 항목을 하나씩 record에 대입하며 아래 블록을 실행합니다.
    for record in records:
        # 오른쪽 식을 계산한 값을 key_part에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        key_part = f"[{record.key}] " if record.key else ""
        # 리스트 끝에 항목 하나를 추가합니다.
        lines.append(f"- {record.id} {record.kind}/{record.status} {key_part}{record.value}")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return CommandResult(True, "\n".join(lines))


# _confirm(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text, ctx.
# 반환 타입 힌트: CommandResult.
def _confirm(text: str, ctx: MemoryCommandContext) -> CommandResult:
    # _MEMORY_CONFIRM.match()의 반환값을 match에 대입합니다.
    match = _MEMORY_CONFIRM.match(text.strip())
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match is None.
    if match is None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, "형식: /memory confirm <id>")

    # match.group()의 반환값을 record_id에 대입합니다.
    record_id = match.group("id")
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # ctx.store.confirm()의 반환값을 confirmed에 대입합니다.
        confirmed = ctx.store.confirm(record_id, _now(ctx.clock))
    # JarvisMemoryError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except JarvisMemoryError as error:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, error.user_message)

    # _emit()을 호출해 작업을 수행합니다.
    _emit(ctx.events, "memory.confirm", {"record_id": record_id, "key": confirmed.key})
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return CommandResult(True, f"확정했습니다. {record_id}", (record_id,))


# _edit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text, ctx.
# 반환 타입 힌트: CommandResult.
def _edit(text: str, ctx: MemoryCommandContext) -> CommandResult:
    # _MEMORY_EDIT.match()의 반환값을 match에 대입합니다.
    match = _MEMORY_EDIT.match(text.strip())
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match is None.
    if match is None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, "형식: /memory edit <id> <새 값>")

    # match.group()의 반환값을 record_id에 대입합니다.
    record_id = match.group("id")
    # match.group('value').strip()의 반환값을 new_value에 대입합니다.
    new_value = match.group("value").strip()
    # ctx.store.get_record()의 반환값을 existing에 대입합니다.
    existing = ctx.store.get_record(record_id)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: existing is None.
    if existing is None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, f"기억 {record_id}을 찾지 못했습니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: existing.status not in {'confirmed',
    # 'candidate'}.
    if existing.status not in {"confirmed", "candidate"}:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, "확정·후보만 수정할 수 있습니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: existing.key is None or not
    # validate_memory_key(existing.key).
    if existing.key is None or not validate_memory_key(existing.key):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, "key가 없는 레코드는 수정할 수 없습니다.")

    # _now()의 반환값을 now에 대입합니다.
    now = _now(ctx.clock)
    # 오른쪽 식을 계산한 값을 kind에 대입합니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    kind: RecordKind = "correction" if existing.status == "confirmed" else "fact"
    # MemoryRecord()의 반환값을 new_record에 대입합니다.
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
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # ctx.store.put_record()을 호출해 작업을 수행합니다.
        ctx.store.put_record(new_record)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: existing.status == 'confirmed'.
        if existing.status == "confirmed":
            # ctx.store.supersede()을 호출해 작업을 수행합니다.
            ctx.store.supersede(existing.id, new_record.id, now)
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # ctx.store.soft_delete()을 호출해 작업을 수행합니다.
            ctx.store.soft_delete(existing.id, "edited", now)
    # JarvisMemoryError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except JarvisMemoryError as error:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, error.user_message)

    # _emit_write()을 호출해 작업을 수행합니다.
    _emit_write(
        ctx.events,
        record_id=new_record.id,
        kind=kind,
        status="confirmed",
        source_kind="user_explicit",
    )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: existing.status == 'confirmed'.
    if existing.status == "confirmed":
        # _emit()을 호출해 작업을 수행합니다.
        _emit(
            ctx.events,
            "memory.supersede",
            {"old_id": existing.id, "new_id": new_record.id, "key": existing.key},
        )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return CommandResult(True, f"수정했습니다. [{existing.key}] {new_value}", (new_record.id,))


# _forget(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text, ctx.
# 반환 타입 힌트: CommandResult.
def _forget(text: str, ctx: MemoryCommandContext) -> CommandResult:
    # _FORGET.match()의 반환값을 match에 대입합니다.
    match = _FORGET.match(text.strip())
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match is None.
    if match is None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, "형식: /forget <id>")

    # match.group()의 반환값을 record_id에 대입합니다.
    record_id = match.group("id")
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # ctx.store.soft_delete()을 호출해 작업을 수행합니다.
        ctx.store.soft_delete(record_id, "user_forget", _now(ctx.clock))
    # JarvisMemoryError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except JarvisMemoryError as error:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, error.user_message)

    # _emit()을 호출해 작업을 수행합니다.
    _emit(ctx.events, "memory.delete", {"record_id": record_id, "reason": "user_forget"})
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return CommandResult(True, f"삭제했습니다. {record_id}", (record_id,))


# _export(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: ctx.
# 반환 타입 힌트: CommandResult.
def _export(ctx: MemoryCommandContext) -> CommandResult:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ctx.export_dir is None.
    if ctx.export_dir is None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CommandResult(False, "내보내기 경로가 설정되지 않았습니다.")
    # ctx.store.export()의 반환값을 export_file에 대입합니다.
    export_file = ctx.store.export(ctx.export_dir, include_raw=False)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return CommandResult(True, f"내보냈습니다. {export_file}")


# try_handle_memory_command(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text, ctx.
# 반환 타입 힌트: CommandResult | None.
def try_handle_memory_command(text: str, ctx: MemoryCommandContext) -> CommandResult | None:
    """Parse and execute memory commands; return None if the line is not a memory command."""
    # text.strip()의 반환값을 stripped에 대입합니다.
    stripped = text.strip()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not stripped.
    if not stripped:
        # None을 반환하고 이 함수의 실행을 끝냅니다.
        return None

    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _REMEMBER_PREFIX.match(stripped).
    if _REMEMBER_PREFIX.match(stripped):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return _remember(stripped, ctx)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _CORRECTION.match(stripped).
    if _CORRECTION.match(stripped):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return _correct(stripped, ctx)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _MEMORY_LIST.match(stripped).
    if _MEMORY_LIST.match(stripped):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return _list_records(stripped, ctx)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _MEMORY_CONFIRM.match(stripped).
    if _MEMORY_CONFIRM.match(stripped):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return _confirm(stripped, ctx)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _MEMORY_EDIT.match(stripped).
    if _MEMORY_EDIT.match(stripped):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return _edit(stripped, ctx)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _FORGET.match(stripped).
    if _FORGET.match(stripped):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return _forget(stripped, ctx)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _MEMORY_EXPORT.match(stripped).
    if _MEMORY_EXPORT.match(stripped):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return _export(ctx)
    # None을 반환하고 이 함수의 실행을 끝냅니다.
    return None

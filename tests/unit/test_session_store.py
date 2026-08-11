"""Tests for Phase 1 session rows and crash-safe raw JSONL."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from app.core.errors import MemoryCorrupted, RecoveryError
from app.core.errors import MemoryError as JarvisMemoryError
from app.llm.base import LLMUsage
from app.memory.migrations import initialize_database
from app.memory.store import RawRecord, SQLiteSessionStore

pytestmark = pytest.mark.phase1
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 14, 30, tzinfo=KST)
SESSION_ID = "ses_01KZQ6CQWDC6W068WDYMT2ZY4C"
TURN_ID = "turn_01KZQ6CQWDC6W068WDYMT2ZY4C"
REQUEST_ID = "req_01KZQ6CQWDC6W068WDYMT2ZY4C"


@pytest.fixture
def session_store(tmp_path: Path) -> SQLiteSessionStore:
    database = tmp_path / "memory" / "jarvis.sqlite3"
    initialize_database(database, created_at=NOW)
    return SQLiteSessionStore(
        database,
        data_root=tmp_path,
        raw_dir=tmp_path / "memory" / "raw",
        quarantine_dir=tmp_path / "state" / "quarantine",
        fsync_raw=False,
    )


def _record(
    *,
    role: str = "user",
    content: str = "안녕하세요",
    tool_call_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> RawRecord:
    return RawRecord(
        ts=NOW,
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        role=cast(Any, role),
        content=content,
        channel="text",
        request_id=REQUEST_ID,
        tool_call_id=tool_call_id,
        meta=meta,
    )


def test_start_session_creates_relative_raw_path_and_is_idempotent(
    session_store: SQLiteSessionStore,
    tmp_path: Path,
) -> None:
    first = session_store.start_session(SESSION_ID, NOW)
    second = session_store.start_session(SESSION_ID, NOW)

    assert first == second
    assert first.raw_path == tmp_path / "memory" / "raw" / f"{SESSION_ID}.jsonl"
    assert first.raw_path.read_bytes() == b""
    assert session_store.unfinished_sessions() == [first]


def test_start_session_rejects_metadata_collision_and_orphan_raw(
    session_store: SQLiteSessionStore,
    tmp_path: Path,
) -> None:
    session_store.start_session(SESSION_ID, NOW)
    with pytest.raises(MemoryCorrupted, match="충돌"):
        session_store.start_session(SESSION_ID, NOW + timedelta(seconds=1))

    other = "ses_01KZQ6CQWDC6W068WDYMT2ZY4D"
    orphan = tmp_path / "memory" / "raw" / f"{other}.jsonl"
    orphan.write_text("existing", encoding="utf-8")
    with pytest.raises(RecoveryError, match="이미 존재"):
        session_store.start_session(other, NOW)


def test_append_and_read_raw_preserves_korean_schema(
    session_store: SQLiteSessionStore,
) -> None:
    session_store.start_session(SESSION_ID, NOW)
    session_store.append_raw(_record(meta={"source": "keyboard"}))
    assistant = RawRecord(
        ts=NOW + timedelta(seconds=1),
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        role="assistant",
        content="반갑습니다",
        channel="text",
        request_id=REQUEST_ID,
    )
    raw_path = session_store.append_raw(assistant)

    result = session_store.read_raw(SESSION_ID)
    assert result.records == (_record(meta={"source": "keyboard"}), assistant)
    assert result.broken_tail is False
    assert result.quarantine_path is None
    serialized = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()]
    assert serialized[0]["content"] == "안녕하세요"
    assert serialized[0]["meta"] == {"source": "keyboard", "request_id": REQUEST_ID}


def test_append_fsyncs_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "memory" / "jarvis.sqlite3"
    initialize_database(database, created_at=NOW)
    store = SQLiteSessionStore(
        database,
        data_root=tmp_path,
        raw_dir=tmp_path / "memory" / "raw",
        quarantine_dir=tmp_path / "state" / "quarantine",
        fsync_raw=True,
    )
    store.start_session(SESSION_ID, NOW)
    calls: list[int] = []
    monkeypatch.setattr("app.memory.store.os.fsync", calls.append)

    store.append_raw(_record())

    assert len(calls) == 1


def test_broken_last_line_is_quarantined_and_valid_prefix_is_kept(
    session_store: SQLiteSessionStore,
) -> None:
    row = session_store.start_session(SESSION_ID, NOW)
    session_store.append_raw(_record())
    with row.raw_path.open("ab") as output:
        output.write(b'{"v":1,"content":"broken')

    result = session_store.read_raw(SESSION_ID)

    assert result.records == (_record(),)
    assert result.broken_tail is True
    assert result.quarantine_path is not None
    assert result.quarantine_path.read_bytes() == b'{"v":1,"content":"broken'
    assert session_store.read_raw(SESSION_ID).records == (_record(),)


def test_existing_tail_gets_numbered_quarantine_path(session_store: SQLiteSessionStore) -> None:
    row = session_store.start_session(SESSION_ID, NOW)
    first_tail = row.raw_path.parents[2] / "state" / "quarantine" / f"{SESSION_ID}.tail"
    first_tail.write_bytes(b"old")
    row.raw_path.write_bytes(b"broken")

    result = session_store.read_raw(SESSION_ID)

    assert result.quarantine_path is not None
    assert result.quarantine_path.name == f"{SESSION_ID}.tail.1"
    assert first_tail.read_bytes() == b"old"


def test_corruption_before_last_line_is_fatal_and_not_rewritten(
    session_store: SQLiteSessionStore,
) -> None:
    row = session_store.start_session(SESSION_ID, NOW)
    valid = json.dumps(_record().as_dict(), ensure_ascii=False).encode() + b"\n"
    original = valid + b"broken\n" + valid
    row.raw_path.write_bytes(original)

    with pytest.raises(MemoryCorrupted) as captured:
        session_store.read_raw(SESSION_ID)

    assert captured.value.detail["line"] == 2
    assert row.raw_path.read_bytes() == original


def test_record_turn_accumulates_decimal_usage_and_closes_session(
    session_store: SQLiteSessionStore,
) -> None:
    session_store.start_session(SESSION_ID, NOW)
    first = session_store.record_turn(
        SESSION_ID,
        LLMUsage(10, 4, Decimal("0.0012"), 20),
    )
    second = session_store.record_turn(
        SESSION_ID,
        LLMUsage(5, 2, Decimal("0.0003"), 10),
    )

    assert first.turn_count == 1
    assert second.turn_count == 2
    assert second.tokens_in == 15
    assert second.tokens_out == 6
    assert second.cost_usd == Decimal("0.0015")

    ended = session_store.end_session(
        SESSION_ID,
        ended_at=NOW + timedelta(minutes=1),
        reason="bye",
    )
    assert ended.end_reason == "bye"
    assert session_store.unfinished_sessions() == []
    assert session_store.end_session(
        SESSION_ID,
        ended_at=NOW + timedelta(minutes=2),
        reason="timeout",
    ) == ended
    with pytest.raises(JarvisMemoryError, match="종료된"):
        session_store.append_raw(_record())


def test_checkpoint_is_idempotent_but_rejects_conflict(
    session_store: SQLiteSessionStore,
) -> None:
    session_store.start_session(SESSION_ID, NOW)
    kwargs = {
        "seq": 1,
        "created_at": NOW,
        "last_turn_id": TURN_ID,
        "turn_count": 3,
        "history_digest": "summary-v1",
    }
    session_store.checkpoint(SESSION_ID, **kwargs)
    session_store.checkpoint(SESSION_ID, **kwargs)

    with pytest.raises(MemoryCorrupted, match="충돌"):
        session_store.checkpoint(SESSION_ID, **{**kwargs, "turn_count": 4})


def test_missing_sessions_and_invalid_records_are_rejected(
    session_store: SQLiteSessionStore,
) -> None:
    assert session_store.get_session(SESSION_ID) is None
    with pytest.raises(JarvisMemoryError):
        session_store.append_raw(_record())
    with pytest.raises(JarvisMemoryError):
        session_store.read_raw(SESSION_ID)
    with pytest.raises(ValueError):
        _record(role="invalid")
    with pytest.raises(ValueError, match="tool_call_id"):
        _record(role="tool")
    with pytest.raises(ValueError, match="tool raw"):
        _record(role="user", tool_call_id="call_1")


def test_raw_mapping_rejects_wrong_schema_and_non_json_meta() -> None:
    value = _record(meta={"bad": object()})
    with pytest.raises(ValueError, match="직렬화"):
        value.as_dict()

    mapping = _record().as_dict()
    mapping["extra"] = True
    with pytest.raises(ValueError, match="스키마"):
        RawRecord.from_mapping(mapping)


def test_database_raw_path_cannot_escape_data_root(
    session_store: SQLiteSessionStore,
) -> None:
    row = session_store.start_session(SESSION_ID, NOW)
    database = row.raw_path.parents[1] / "jarvis.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "UPDATE sessions SET raw_path = ? WHERE session_id = ?",
            ("..\\..\\outside.jsonl", SESSION_ID),
        )

    with pytest.raises(RecoveryError, match="data_root 밖"):
        session_store.get_session(SESSION_ID)


def test_raw_record_for_another_session_is_corruption(
    session_store: SQLiteSessionStore,
) -> None:
    row = session_store.start_session(SESSION_ID, NOW)
    foreign = _record().as_dict()
    foreign["session_id"] = "ses_01KZQ6CQWDC6W068WDYMT2ZY4D"
    row.raw_path.write_text(json.dumps(foreign) + "\n", encoding="utf-8")

    with pytest.raises(MemoryCorrupted, match="session_id"):
        session_store.read_raw(SESSION_ID)


def test_session_row_rejects_negative_accumulators(
    session_store: SQLiteSessionStore,
) -> None:
    row = session_store.start_session(SESSION_ID, NOW)
    database = row.raw_path.parents[1] / "jarvis.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "UPDATE sessions SET tokens_in = -1 WHERE session_id = ?",
            (SESSION_ID,),
        )

    with pytest.raises(MemoryCorrupted, match="누적값"):
        session_store.get_session(SESSION_ID)

"""Tests for Phase 2 memory record persistence and search."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import ClassVar

import pytest

from app.core.errors import MemoryError as JarvisMemoryError
from app.memory.migrations import initialize_database
from app.memory.models import MemoryQuery, MemoryRecord, new_fact_id
from app.memory.retrieval import fts_match_query
from app.memory.store import SQLiteSessionStore

pytestmark = pytest.mark.phase2
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 14, 30, tzinfo=KST)
SESSION_ID = "ses_01KZQ6CQWDC6W068WDYMT2ZY4C"
TURN_ID = "turn_01KZQ6CQWDC6W068WDYMT2ZY4C"


class _RetrievalSettings:
    top_k = 8
    min_score = 0.0
    include_candidates = True
    max_candidates = 3
    kind_weights: ClassVar[dict[str, float]] = {
        "correction": 1.0,
        "fact": 0.9,
        "summary": 0.6,
        "doc_chunk": 0.5,
    }
    half_life_days: ClassVar[dict[str, int]] = {
        "correction": 365,
        "fact": 180,
        "summary": 30,
        "doc_chunk": 3650,
    }
    fts_weight = 0.6
    embedding_weight = 0.4


@pytest.fixture
def memory_store(tmp_path: Path) -> SQLiteSessionStore:
    database = tmp_path / "memory" / "jarvis.sqlite3"
    initialize_database(database, created_at=NOW)
    return SQLiteSessionStore(
        database,
        data_root=tmp_path,
        raw_dir=tmp_path / "memory" / "raw",
        quarantine_dir=tmp_path / "state" / "quarantine",
        fsync_raw=False,
        retrieval_settings=_RetrievalSettings(),
        key_aliases={
            "pref.answer_style": ["말투", "답변 스타일"],
        },
    )


def _fact(
    *,
    record_id: str | None = None,
    key: str = "pref.answer_style",
    value: str = "짧고 근거 포함",
    status: str = "confirmed",
    updated_at: datetime | None = None,
) -> MemoryRecord:
    stamp = updated_at or NOW
    return MemoryRecord(
        id=record_id or new_fact_id(),
        schema_version=1,
        kind="fact",
        key=key,
        value=value,
        status=status,  # type: ignore[arg-type]
        source_session_id=SESSION_ID,
        source_turn_id=TURN_ID,
        source_kind="user_explicit",
        created_at=stamp,
        updated_at=stamp,
        expires_at=None,
        sensitivity="normal",
        supersedes=None,
        tags=("preference",),
    )


def test_unique_confirmed_key_invariant(memory_store: SQLiteSessionStore) -> None:
    first = _fact(record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4A")
    second = _fact(record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4B")

    memory_store.put_record(first)
    with pytest.raises(JarvisMemoryError, match="confirmed"):
        memory_store.put_record(second)


def test_put_record_idempotent_same_id(memory_store: SQLiteSessionStore) -> None:
    record = _fact(record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4A")
    first = memory_store.put_record(record)
    second = memory_store.put_record(record)

    assert first == second == record.id
    assert len(memory_store.list_records(status="confirmed")) == 1


def test_confirm_candidate(memory_store: SQLiteSessionStore) -> None:
    candidate = _fact(
        record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4A",
        status="candidate",
    )
    memory_store.put_record(candidate)
    confirmed = memory_store.confirm(candidate.id, NOW + timedelta(minutes=1))

    assert confirmed.status == "confirmed"
    stored = memory_store.get_record(candidate.id)
    assert stored is not None
    assert stored.status == "confirmed"


def test_forget_removes_from_fts_and_embeddings(memory_store: SQLiteSessionStore) -> None:
    unique_value = "phase2_forget_marker_token_xyz"
    record = _fact(
        record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4A",
        value=unique_value,
    )
    memory_store.put_record(record)

    database = memory_store._database_path
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            """
            INSERT INTO embeddings(record_id, model, dim, vector, created_at)
            VALUES (?, 'test-model', 4, ?, ?)
            """,
            (record.id, b"\x00\x00\x00\x00", NOW.isoformat(timespec="milliseconds")),
        )
        fts_query = fts_match_query(unique_value)
        before = connection.execute(
            """
            SELECT COUNT(*) FROM records_fts
            JOIN records r ON r.rowid = records_fts.rowid
            WHERE records_fts MATCH ? AND r.id = ?
            """,
            (fts_query, record.id),
        ).fetchone()[0]
        assert before == 1

    memory_store.soft_delete(record.id, "user request", NOW + timedelta(minutes=2))

    with closing(sqlite3.connect(database)) as connection, connection:
        fts_query = fts_match_query(unique_value)
        after = connection.execute(
            """
            SELECT COUNT(*) FROM records_fts
            JOIN records r ON r.rowid = records_fts.rowid
            WHERE records_fts MATCH ? AND r.id = ?
            """,
            (fts_query, record.id),
        ).fetchone()[0]
        embedding = connection.execute(
            "SELECT 1 FROM embeddings WHERE record_id = ?", (record.id,)
        ).fetchone()
        deleted = connection.execute(
            "SELECT status, delete_reason FROM records WHERE id = ?", (record.id,)
        ).fetchone()

    assert after == 0
    assert embedding is None
    assert deleted == ("deleted", "user request")

    search = memory_store.search(MemoryQuery(text=unique_value))
    assert all(item.record.id != record.id for item in search.matches)


def test_invalid_transition_rejected(memory_store: SQLiteSessionStore) -> None:
    confirmed = _fact(record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4A")
    memory_store.put_record(confirmed)

    with pytest.raises(JarvisMemoryError, match="전이"):
        memory_store.confirm(confirmed.id, NOW)

    superseded = _fact(
        record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4B",
        key="pref.language",
    )
    memory_store.put_record(superseded)
    memory_store.supersede(superseded.id, confirmed.id, NOW + timedelta(minutes=1))

    with pytest.raises(JarvisMemoryError, match="전이"):
        memory_store.confirm(superseded.id, NOW + timedelta(minutes=2))

    memory_store.soft_delete(confirmed.id, "cleanup", NOW + timedelta(minutes=3))
    with pytest.raises(JarvisMemoryError, match="전이"):
        memory_store.confirm(confirmed.id, NOW + timedelta(minutes=4))

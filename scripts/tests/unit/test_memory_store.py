# 파이썬 공부 | scripts/tests/unit/test_memory_store.py
# memory_store 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase2
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 14, 30, tzinfo=KST)
# SESSION_ID에 문자열을 대입합니다.
SESSION_ID = "ses_01KZQ6CQWDC6W068WDYMT2ZY4C"
# TURN_ID에 문자열을 대입합니다.
TURN_ID = "turn_01KZQ6CQWDC6W068WDYMT2ZY4C"


# _RetrievalSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class _RetrievalSettings:
    # top_k에 숫자 등 고정된 값을 대입합니다.
    top_k = 8
    # min_score에 숫자 등 고정된 값을 대입합니다.
    min_score = 0.0
    # include_candidates을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    include_candidates = True
    # max_candidates에 숫자 등 고정된 값을 대입합니다.
    max_candidates = 3
    # kind_weights에 딕셔너리(키와 값의 쌍)을 대입합니다.
    kind_weights: ClassVar[dict[str, float]] = {
        "correction": 1.0,
        "fact": 0.9,
        "summary": 0.6,
        "doc_chunk": 0.5,
    }
    # half_life_days에 딕셔너리(키와 값의 쌍)을 대입합니다.
    half_life_days: ClassVar[dict[str, int]] = {
        "correction": 365,
        "fact": 180,
        "summary": 30,
        "doc_chunk": 3650,
    }
    # fts_weight에 숫자 등 고정된 값을 대입합니다.
    fts_weight = 0.6
    # embedding_weight에 숫자 등 고정된 값을 대입합니다.
    embedding_weight = 0.4


# memory_store(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: SQLiteSessionStore.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def memory_store(tmp_path: Path) -> SQLiteSessionStore:
    # 오른쪽 식을 계산한 값을 database에 대입합니다.
    database = tmp_path / "memory" / "jarvis.sqlite3"
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(database, created_at=NOW)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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


# _fact(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: record_id, key, value, status, updated_at.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: MemoryRecord.
def _fact(
    *,
    record_id: str | None = None,
    key: str = "pref.answer_style",
    value: str = "짧고 근거 포함",
    status: str = "confirmed",
    updated_at: datetime | None = None,
) -> MemoryRecord:
    # 오른쪽 식을 계산한 값을 stamp에 대입합니다.
    stamp = updated_at or NOW
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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


# pytest가 test_unique_confirmed_key_invariant()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: memory_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_unique_confirmed_key_invariant(memory_store: SQLiteSessionStore) -> None:
    # _fact()의 반환값을 first에 대입합니다.
    first = _fact(record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4A")
    # _fact()의 반환값을 second에 대입합니다.
    second = _fact(record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4B")

    # memory_store.put_record()을 호출해 작업을 수행합니다.
    memory_store.put_record(first)
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(JarvisMemoryError, match="confirmed"):
        # memory_store.put_record()을 호출해 작업을 수행합니다.
        memory_store.put_record(second)


# pytest가 test_put_record_idempotent_same_id()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: memory_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_put_record_idempotent_same_id(memory_store: SQLiteSessionStore) -> None:
    # _fact()의 반환값을 record에 대입합니다.
    record = _fact(record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4A")
    # memory_store.put_record()의 반환값을 first에 대입합니다.
    first = memory_store.put_record(record)
    # memory_store.put_record()의 반환값을 second에 대입합니다.
    second = memory_store.put_record(record)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first == second == record.id
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(memory_store.list_records(status="confirmed")) == 1


# pytest가 test_confirm_candidate()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: memory_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_confirm_candidate(memory_store: SQLiteSessionStore) -> None:
    # _fact()의 반환값을 candidate에 대입합니다.
    candidate = _fact(
        record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4A",
        status="candidate",
    )
    # memory_store.put_record()을 호출해 작업을 수행합니다.
    memory_store.put_record(candidate)
    # memory_store.confirm()의 반환값을 confirmed에 대입합니다.
    confirmed = memory_store.confirm(candidate.id, NOW + timedelta(minutes=1))

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert confirmed.status == "confirmed"
    # memory_store.get_record()의 반환값을 stored에 대입합니다.
    stored = memory_store.get_record(candidate.id)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert stored is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert stored.status == "confirmed"


# pytest가 test_forget_removes_from_fts_and_embeddings()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: memory_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_forget_removes_from_fts_and_embeddings(memory_store: SQLiteSessionStore) -> None:
    # unique_value에 문자열을 대입합니다.
    unique_value = "phase2_forget_marker_token_xyz"
    # _fact()의 반환값을 record에 대입합니다.
    record = _fact(
        record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4A",
        value=unique_value,
    )
    # memory_store.put_record()을 호출해 작업을 수행합니다.
    memory_store.put_record(record)

    # 오른쪽 식을 계산한 값을 database에 대입합니다.
    database = memory_store._database_path
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with closing(sqlite3.connect(database)) as connection, connection:
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute(
            """
            INSERT INTO embeddings(record_id, model, dim, vector, created_at)
            VALUES (?, 'test-model', 4, ?, ?)
            """,
            (record.id, b"\x00\x00\x00\x00", NOW.isoformat(timespec="milliseconds")),
        )
        # fts_match_query()의 반환값을 fts_query에 대입합니다.
        fts_query = fts_match_query(unique_value)
        # 오른쪽 식을 계산한 값을 before에 대입합니다.
        before = connection.execute(
            """
            SELECT COUNT(*) FROM records_fts
            JOIN records r ON r.rowid = records_fts.rowid
            WHERE records_fts MATCH ? AND r.id = ?
            """,
            (fts_query, record.id),
        ).fetchone()[0]
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert before == 1

    # memory_store.soft_delete()을 호출해 작업을 수행합니다.
    memory_store.soft_delete(record.id, "user request", NOW + timedelta(minutes=2))

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with closing(sqlite3.connect(database)) as connection, connection:
        # fts_match_query()의 반환값을 fts_query에 대입합니다.
        fts_query = fts_match_query(unique_value)
        # 오른쪽 식을 계산한 값을 after에 대입합니다.
        after = connection.execute(
            """
            SELECT COUNT(*) FROM records_fts
            JOIN records r ON r.rowid = records_fts.rowid
            WHERE records_fts MATCH ? AND r.id = ?
            """,
            (fts_query, record.id),
        ).fetchone()[0]
        # 아래 함수()의 반환값을 embedding에 대입합니다.
        embedding = connection.execute(
            "SELECT 1 FROM embeddings WHERE record_id = ?", (record.id,)
        ).fetchone()
        # 아래 함수()의 반환값을 deleted에 대입합니다.
        deleted = connection.execute(
            "SELECT status, delete_reason FROM records WHERE id = ?", (record.id,)
        ).fetchone()

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert after == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert embedding is None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert deleted == ("deleted", "user request")

    # memory_store.search()의 반환값을 search에 대입합니다.
    search = memory_store.search(MemoryQuery(text=unique_value))
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert all(item.record.id != record.id for item in search.matches)


# pytest가 test_invalid_transition_rejected()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: memory_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_invalid_transition_rejected(memory_store: SQLiteSessionStore) -> None:
    # _fact()의 반환값을 confirmed에 대입합니다.
    confirmed = _fact(record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4A")
    # memory_store.put_record()을 호출해 작업을 수행합니다.
    memory_store.put_record(confirmed)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(JarvisMemoryError, match="전이"):
        # memory_store.confirm()을 호출해 작업을 수행합니다.
        memory_store.confirm(confirmed.id, NOW)

    # _fact()의 반환값을 superseded에 대입합니다.
    superseded = _fact(
        record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4B",
        key="pref.language",
    )
    # memory_store.put_record()을 호출해 작업을 수행합니다.
    memory_store.put_record(superseded)
    # memory_store.supersede()을 호출해 작업을 수행합니다.
    memory_store.supersede(superseded.id, confirmed.id, NOW + timedelta(minutes=1))

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(JarvisMemoryError, match="전이"):
        # memory_store.confirm()을 호출해 작업을 수행합니다.
        memory_store.confirm(superseded.id, NOW + timedelta(minutes=2))

    # memory_store.soft_delete()을 호출해 작업을 수행합니다.
    memory_store.soft_delete(confirmed.id, "cleanup", NOW + timedelta(minutes=3))
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(JarvisMemoryError, match="전이"):
        # memory_store.confirm()을 호출해 작업을 수행합니다.
        memory_store.confirm(confirmed.id, NOW + timedelta(minutes=4))

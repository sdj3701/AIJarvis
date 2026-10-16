# 파이썬 공부 | scripts/tests/unit/test_session_store.py
# session_store 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase1
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 14, 30, tzinfo=KST)
# SESSION_ID에 문자열을 대입합니다.
SESSION_ID = "ses_01KZQ6CQWDC6W068WDYMT2ZY4C"
# TURN_ID에 문자열을 대입합니다.
TURN_ID = "turn_01KZQ6CQWDC6W068WDYMT2ZY4C"
# REQUEST_ID에 문자열을 대입합니다.
REQUEST_ID = "req_01KZQ6CQWDC6W068WDYMT2ZY4C"


# session_store(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: SQLiteSessionStore.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def session_store(tmp_path: Path) -> SQLiteSessionStore:
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
    )


# _record(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: role, content, tool_call_id, meta.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: RawRecord.
def _record(
    *,
    role: str = "user",
    content: str = "안녕하세요",
    tool_call_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> RawRecord:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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


# pytest가 test_start_session_creates_relative_raw_path_and_is_idempotent()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: session_store, tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_start_session_creates_relative_raw_path_and_is_idempotent(
    session_store: SQLiteSessionStore,
    tmp_path: Path,
) -> None:
    # session_store.start_session()의 반환값을 first에 대입합니다.
    first = session_store.start_session(SESSION_ID, NOW)
    # session_store.start_session()의 반환값을 second에 대입합니다.
    second = session_store.start_session(SESSION_ID, NOW)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first == second
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first.raw_path == tmp_path / "memory" / "raw" / f"{SESSION_ID}.jsonl"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first.raw_path.read_bytes() == b""
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert session_store.unfinished_sessions() == [first]


# pytest가 test_start_session_rejects_metadata_collision_and_orphan_raw()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: session_store, tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_start_session_rejects_metadata_collision_and_orphan_raw(
    session_store: SQLiteSessionStore,
    tmp_path: Path,
) -> None:
    # session_store.start_session()을 호출해 작업을 수행합니다.
    session_store.start_session(SESSION_ID, NOW)
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(MemoryCorrupted, match="충돌"):
        # session_store.start_session()을 호출해 작업을 수행합니다.
        session_store.start_session(SESSION_ID, NOW + timedelta(seconds=1))

    # other에 문자열을 대입합니다.
    other = "ses_01KZQ6CQWDC6W068WDYMT2ZY4D"
    # 오른쪽 식을 계산한 값을 orphan에 대입합니다.
    orphan = tmp_path / "memory" / "raw" / f"{other}.jsonl"
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    orphan.write_text("existing", encoding="utf-8")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(RecoveryError, match="이미 존재"):
        # session_store.start_session()을 호출해 작업을 수행합니다.
        session_store.start_session(other, NOW)


# pytest가 test_append_and_read_raw_preserves_korean_schema()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: session_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_append_and_read_raw_preserves_korean_schema(
    session_store: SQLiteSessionStore,
) -> None:
    # session_store.start_session()을 호출해 작업을 수행합니다.
    session_store.start_session(SESSION_ID, NOW)
    # session_store.append_raw()을 호출해 작업을 수행합니다.
    session_store.append_raw(_record(meta={"source": "keyboard"}))
    # RawRecord()의 반환값을 assistant에 대입합니다.
    assistant = RawRecord(
        ts=NOW + timedelta(seconds=1),
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        role="assistant",
        content="반갑습니다",
        channel="text",
        request_id=REQUEST_ID,
    )
    # session_store.append_raw()의 반환값을 raw_path에 대입합니다.
    raw_path = session_store.append_raw(assistant)

    # session_store.read_raw()의 반환값을 result에 대입합니다.
    result = session_store.read_raw(SESSION_ID)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.records == (_record(meta={"source": "keyboard"}), assistant)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.broken_tail is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.quarantine_path is None
    # 오른쪽 식을 계산한 값을 serialized에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    serialized = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert serialized[0]["content"] == "안녕하세요"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert serialized[0]["meta"] == {"source": "keyboard", "request_id": REQUEST_ID}


# pytest가 test_append_fsyncs_when_enabled()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: tmp_path, monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_append_fsyncs_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 오른쪽 식을 계산한 값을 database에 대입합니다.
    database = tmp_path / "memory" / "jarvis.sqlite3"
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(database, created_at=NOW)
    # SQLiteSessionStore()의 반환값을 store에 대입합니다.
    store = SQLiteSessionStore(
        database,
        data_root=tmp_path,
        raw_dir=tmp_path / "memory" / "raw",
        quarantine_dir=tmp_path / "state" / "quarantine",
        fsync_raw=True,
    )
    # store.start_session()을 호출해 작업을 수행합니다.
    store.start_session(SESSION_ID, NOW)
    # calls에 리스트(순서가 있고 수정 가능)을 대입합니다.
    calls: list[int] = []
    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr("app.memory.store.os.fsync", calls.append)

    # store.append_raw()을 호출해 작업을 수행합니다.
    store.append_raw(_record())

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(calls) == 1


# pytest가 test_broken_last_line_is_quarantined_and_valid_prefix_is_kept()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: session_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_broken_last_line_is_quarantined_and_valid_prefix_is_kept(
    session_store: SQLiteSessionStore,
) -> None:
    # session_store.start_session()의 반환값을 row에 대입합니다.
    row = session_store.start_session(SESSION_ID, NOW)
    # session_store.append_raw()을 호출해 작업을 수행합니다.
    session_store.append_raw(_record())
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with row.raw_path.open("ab") as output:
        # 열린 출력 대상에 데이터를 기록합니다.
        output.write(b'{"v":1,"content":"broken')

    # session_store.read_raw()의 반환값을 result에 대입합니다.
    result = session_store.read_raw(SESSION_ID)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.records == (_record(),)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.broken_tail is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.quarantine_path is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.quarantine_path.read_bytes() == b'{"v":1,"content":"broken'
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert session_store.read_raw(SESSION_ID).records == (_record(),)


# pytest가 test_existing_tail_gets_numbered_quarantine_path()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: session_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_existing_tail_gets_numbered_quarantine_path(session_store: SQLiteSessionStore) -> None:
    # session_store.start_session()의 반환값을 row에 대입합니다.
    row = session_store.start_session(SESSION_ID, NOW)
    # 오른쪽 식을 계산한 값을 first_tail에 대입합니다.
    first_tail = row.raw_path.parents[2] / "state" / "quarantine" / f"{SESSION_ID}.tail"
    # 바이트 데이터를 파일에 기록합니다.
    first_tail.write_bytes(b"old")
    # 바이트 데이터를 파일에 기록합니다.
    row.raw_path.write_bytes(b"broken")

    # session_store.read_raw()의 반환값을 result에 대입합니다.
    result = session_store.read_raw(SESSION_ID)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.quarantine_path is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.quarantine_path.name == f"{SESSION_ID}.tail.1"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first_tail.read_bytes() == b"old"


# pytest가 test_corruption_before_last_line_is_fatal_and_not_rewritten()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: session_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_corruption_before_last_line_is_fatal_and_not_rewritten(
    session_store: SQLiteSessionStore,
) -> None:
    # session_store.start_session()의 반환값을 row에 대입합니다.
    row = session_store.start_session(SESSION_ID, NOW)
    # 오른쪽 식을 계산한 값을 valid에 대입합니다.
    valid = json.dumps(_record().as_dict(), ensure_ascii=False).encode() + b"\n"
    # 오른쪽 식을 계산한 값을 original에 대입합니다.
    original = valid + b"broken\n" + valid
    # 바이트 데이터를 파일에 기록합니다.
    row.raw_path.write_bytes(original)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(MemoryCorrupted) as captured:
        # session_store.read_raw()을 호출해 작업을 수행합니다.
        session_store.read_raw(SESSION_ID)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured.value.detail["line"] == 2
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert row.raw_path.read_bytes() == original


# pytest가 test_record_turn_accumulates_decimal_usage_and_closes_session()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: session_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_record_turn_accumulates_decimal_usage_and_closes_session(
    session_store: SQLiteSessionStore,
) -> None:
    # session_store.start_session()을 호출해 작업을 수행합니다.
    session_store.start_session(SESSION_ID, NOW)
    # session_store.record_turn()의 반환값을 first에 대입합니다.
    first = session_store.record_turn(
        SESSION_ID,
        LLMUsage(10, 4, Decimal("0.0012"), 20),
    )
    # session_store.record_turn()의 반환값을 second에 대입합니다.
    second = session_store.record_turn(
        SESSION_ID,
        LLMUsage(5, 2, Decimal("0.0003"), 10),
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first.turn_count == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert second.turn_count == 2
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert second.tokens_in == 15
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert second.tokens_out == 6
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert second.cost_usd == Decimal("0.0015")

    # session_store.end_session()의 반환값을 ended에 대입합니다.
    ended = session_store.end_session(
        SESSION_ID,
        ended_at=NOW + timedelta(minutes=1),
        reason="bye",
    )
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ended.end_reason == "bye"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert session_store.unfinished_sessions() == []
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert session_store.end_session(
        SESSION_ID,
        ended_at=NOW + timedelta(minutes=2),
        reason="timeout",
    ) == ended
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(JarvisMemoryError, match="종료된"):
        # session_store.append_raw()을 호출해 작업을 수행합니다.
        session_store.append_raw(_record())


# pytest가 test_checkpoint_is_idempotent_but_rejects_conflict()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: session_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_checkpoint_is_idempotent_but_rejects_conflict(
    session_store: SQLiteSessionStore,
) -> None:
    # session_store.start_session()을 호출해 작업을 수행합니다.
    session_store.start_session(SESSION_ID, NOW)
    # kwargs에 딕셔너리(키와 값의 쌍)을 대입합니다.
    kwargs = {
        "seq": 1,
        "created_at": NOW,
        "last_turn_id": TURN_ID,
        "turn_count": 3,
        "history_digest": "summary-v1",
    }
    # session_store.checkpoint()을 호출해 작업을 수행합니다.
    session_store.checkpoint(SESSION_ID, **kwargs)
    # session_store.checkpoint()을 호출해 작업을 수행합니다.
    session_store.checkpoint(SESSION_ID, **kwargs)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(MemoryCorrupted, match="충돌"):
        # session_store.checkpoint()을 호출해 작업을 수행합니다.
        session_store.checkpoint(SESSION_ID, **{**kwargs, "turn_count": 4})


# pytest가 test_missing_sessions_and_invalid_records_are_rejected()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: session_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_missing_sessions_and_invalid_records_are_rejected(
    session_store: SQLiteSessionStore,
) -> None:
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert session_store.get_session(SESSION_ID) is None
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(JarvisMemoryError):
        # session_store.append_raw()을 호출해 작업을 수행합니다.
        session_store.append_raw(_record())
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(JarvisMemoryError):
        # session_store.read_raw()을 호출해 작업을 수행합니다.
        session_store.read_raw(SESSION_ID)
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError):
        # _record()을 호출해 작업을 수행합니다.
        _record(role="invalid")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="tool_call_id"):
        # _record()을 호출해 작업을 수행합니다.
        _record(role="tool")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="tool raw"):
        # _record()을 호출해 작업을 수행합니다.
        _record(role="user", tool_call_id="call_1")


# pytest가 test_raw_mapping_rejects_wrong_schema_and_non_json_meta()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_raw_mapping_rejects_wrong_schema_and_non_json_meta() -> None:
    # _record()의 반환값을 value에 대입합니다.
    value = _record(meta={"bad": object()})
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="직렬화"):
        # value.as_dict()을 호출해 작업을 수행합니다.
        value.as_dict()

    # _record().as_dict()의 반환값을 mapping에 대입합니다.
    mapping = _record().as_dict()
    # mapping['extra']을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    mapping["extra"] = True
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="스키마"):
        # RawRecord.from_mapping()을 호출해 작업을 수행합니다.
        RawRecord.from_mapping(mapping)


# pytest가 test_database_raw_path_cannot_escape_data_root()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: session_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_database_raw_path_cannot_escape_data_root(
    session_store: SQLiteSessionStore,
) -> None:
    # session_store.start_session()의 반환값을 row에 대입합니다.
    row = session_store.start_session(SESSION_ID, NOW)
    # 오른쪽 식을 계산한 값을 database에 대입합니다.
    database = row.raw_path.parents[1] / "jarvis.sqlite3"
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with closing(sqlite3.connect(database)) as connection, connection:
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute(
            "UPDATE sessions SET raw_path = ? WHERE session_id = ?",
            ("..\\..\\outside.jsonl", SESSION_ID),
        )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(RecoveryError, match="data_root 밖"):
        # session_store.get_session()을 호출해 작업을 수행합니다.
        session_store.get_session(SESSION_ID)


# pytest가 test_raw_record_for_another_session_is_corruption()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: session_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_raw_record_for_another_session_is_corruption(
    session_store: SQLiteSessionStore,
) -> None:
    # session_store.start_session()의 반환값을 row에 대입합니다.
    row = session_store.start_session(SESSION_ID, NOW)
    # _record().as_dict()의 반환값을 foreign에 대입합니다.
    foreign = _record().as_dict()
    # foreign['session_id']에 문자열을 대입합니다.
    foreign["session_id"] = "ses_01KZQ6CQWDC6W068WDYMT2ZY4D"
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    row.raw_path.write_text(json.dumps(foreign) + "\n", encoding="utf-8")

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(MemoryCorrupted, match="session_id"):
        # session_store.read_raw()을 호출해 작업을 수행합니다.
        session_store.read_raw(SESSION_ID)


# pytest가 test_session_row_rejects_negative_accumulators()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: session_store.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_session_row_rejects_negative_accumulators(
    session_store: SQLiteSessionStore,
) -> None:
    # session_store.start_session()의 반환값을 row에 대입합니다.
    row = session_store.start_session(SESSION_ID, NOW)
    # 오른쪽 식을 계산한 값을 database에 대입합니다.
    database = row.raw_path.parents[1] / "jarvis.sqlite3"
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with closing(sqlite3.connect(database)) as connection, connection:
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute(
            "UPDATE sessions SET tokens_in = -1 WHERE session_id = ?",
            (SESSION_ID,),
        )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(MemoryCorrupted, match="누적값"):
        # session_store.get_session()을 호출해 작업을 수행합니다.
        session_store.get_session(SESSION_ID)

# 파이썬 공부 | scripts/app/memory/store.py
# 대화 세션과 기억을 데이터베이스 및 파일에 저장하고 읽습니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Phase 1 session state and crash-safe raw conversation storage."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock
from typing import Any, Literal, cast

from app.config.models import RetrievalSettings
from app.core.atomic import write_atomic
from app.core.errors import MemoryCorrupted, RecoveryError
from app.core.errors import MemoryError as JarvisMemoryError
from app.llm.base import LLMUsage
from app.memory.migrations import configure_connection
from app.memory.models import (
    MemoryQuery,
    MemoryRecord,
    MemorySearchResult,
    RecordKind,
    RecordStatus,
    ScoredRecord,
    assert_transition_allowed,
)
from app.memory.retrieval import (
    extract_key_candidates,
    finalize_search,
    fts_match_query,
    normalize_bm25,
    score_record,
)

# 오른쪽 식을 계산한 값을 RawRole에 대입합니다.
RawRole = Literal["user", "assistant", "tool", "system_note"]
# 오른쪽 식을 계산한 값을 Channel에 대입합니다.
Channel = Literal["text", "voice"]
# 오른쪽 식을 계산한 값을 EndReason에 대입합니다.
EndReason = Literal["bye", "crash_recovered", "discarded", "timeout"]

# _ULID_PATTERN에 문자열을 대입합니다.
_ULID_PATTERN = r"[0-9A-HJKMNP-TV-Z]{26}"
# frozenset()의 반환값을 _RAW_KEYS에 대입합니다.
_RAW_KEYS = frozenset(
    {
        "v",
        "ts",
        "session_id",
        "turn_id",
        "role",
        "content",
        "channel",
        "tool_call_id",
        "untrusted",
        "meta",
    }
)


# RawRecord: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class RawRecord:
    # ts: datetime 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ts: datetime
    # session_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    session_id: str
    # turn_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    turn_id: str
    # role: RawRole 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    role: RawRole
    # content: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    content: str
    # channel: Channel 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    channel: Channel
    # request_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    request_id: str
    # tool_call_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    tool_call_id: str | None = None
    # untrusted을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    untrusted: bool = False
    # meta을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    meta: Mapping[str, Any] | None = None

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # _validate_time()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_time(self.ts, "ts")
        # _validate_id()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_id(self.session_id, "ses")
        # _validate_id()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_id(self.turn_id, "turn")
        # _validate_id()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_id(self.request_id, "req")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.role not in {'user', 'assistant',
        # 'tool',
        # 'system_note'}.
        if self.role not in {"user", "assistant", "tool", "system_note"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("raw role이 올바르지 않습니다")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.channel not in {'text', 'voice'}.
        if self.channel not in {"text", "voice"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("raw channel이 올바르지 않습니다")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(self.content, str).
        if not isinstance(self.content, str):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError("raw content는 문자열이어야 합니다")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(self.untrusted, bool).
        if not isinstance(self.untrusted, bool):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError("raw untrusted는 bool이어야 합니다")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.role == 'tool' and (not
        # self.tool_call_id).
        if self.role == "tool" and not self.tool_call_id:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("tool raw 레코드에는 tool_call_id가 필요합니다")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.role != 'tool' and
        # self.tool_call_id is not None.
        if self.role != "tool" and self.tool_call_id is not None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("tool_call_id는 tool raw 레코드에만 허용됩니다")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.meta is not None and (not
        # isinstance(self.meta,
        # Mapping)).
        if self.meta is not None and not isinstance(self.meta, Mapping):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError("raw meta는 객체여야 합니다")

    # as_dict(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: dict[str, Any].
    def as_dict(self) -> dict[str, Any]:
        # dict()의 반환값을 meta에 대입합니다.
        meta = dict(self.meta or {})
        # 오른쪽 식을 계산한 값을 meta['request_id']에 대입합니다.
        meta["request_id"] = self.request_id
        # record에 딕셔너리(키와 값의 쌍)을 대입합니다.
        record = {
            "v": 1,
            "ts": self.ts.isoformat(timespec="milliseconds"),
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "role": self.role,
            "content": self.content,
            "channel": self.channel,
            "tool_call_id": self.tool_call_id,
            "untrusted": self.untrusted,
            "meta": meta,
        }
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # json.dumps()을 호출해 작업을 수행합니다.
            json.dumps(record, ensure_ascii=False, allow_nan=False)
        # (TypeError, ValueError)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except (TypeError, ValueError) as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("raw meta는 JSON으로 직렬화할 수 있어야 합니다") from error
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return record

    # from_mapping(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # cls는 이 메서드를 호출한 클래스입니다.
    # 입력: value.
    # 반환 타입 힌트: RawRecord.
    # @classmethod: 객체 대신 클래스를 첫 인자로 받습니다.
    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RawRecord:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: set(value) != _RAW_KEYS or
        # value.get('v') != 1.
        if set(value) != _RAW_KEYS or value.get("v") != 1:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("raw 레코드 스키마가 올바르지 않습니다")
        # value.get()의 반환값을 meta에 대입합니다.
        meta = value.get("meta")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(meta, dict).
        if not isinstance(meta, dict):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("raw meta가 올바르지 않습니다")
        # meta.get()의 반환값을 request_id에 대입합니다.
        request_id = meta.get("request_id")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(request_id, str).
        if not isinstance(request_id, str):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("raw meta.request_id가 올바르지 않습니다")
        # value.get()의 반환값을 timestamp에 대입합니다.
        timestamp = value.get("ts")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(timestamp, str).
        if not isinstance(timestamp, str):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("raw ts가 올바르지 않습니다")
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # datetime.fromisoformat()의 반환값을 parsed_time에 대입합니다.
            parsed_time = datetime.fromisoformat(timestamp)
        # ValueError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except ValueError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("raw ts가 올바르지 않습니다") from error
        # 오른쪽 식을 계산한 값을 extra_meta에 대입합니다.
        # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
        extra_meta = {key: item for key, item in meta.items() if key != "request_id"}
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return cls(
            ts=parsed_time,
            session_id=_required_string(value.get("session_id"), "session_id"),
            turn_id=_required_string(value.get("turn_id"), "turn_id"),
            role=cast(RawRole, value.get("role")),
            content=cast(str, value.get("content")),
            channel=cast(Channel, value.get("channel")),
            request_id=request_id,
            tool_call_id=cast(str | None, value.get("tool_call_id")),
            untrusted=cast(bool, value.get("untrusted")),
            meta=extra_meta or None,
        )


# RawReadResult: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class RawReadResult:
    # records: tuple[RawRecord, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    records: tuple[RawRecord, ...]
    # broken_tail: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    broken_tail: bool
    # quarantine_path: Path | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    quarantine_path: Path | None


# SessionRow: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class SessionRow:
    # session_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    session_id: str
    # started_at: datetime 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    started_at: datetime
    # ended_at: datetime | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ended_at: datetime | None
    # end_reason: EndReason | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    end_reason: EndReason | None
    # turn_count: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    turn_count: int
    # raw_path: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    raw_path: Path
    # cost_usd: Decimal 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    cost_usd: Decimal
    # tokens_in: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    tokens_in: int
    # tokens_out: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    tokens_out: int


# SQLiteSessionStore: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class SQLiteSessionStore:
    """Session rows, raw JSONL, and Phase 2 memory records in one SQLite store."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: database_path, data_root, raw_dir, quarantine_dir, fsync_raw, export_dir,
    # retrieval_settings, key_aliases.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        database_path: Path,
        *,
        data_root: Path,
        raw_dir: Path,
        quarantine_dir: Path,
        fsync_raw: bool,
        export_dir: Path | None = None,
        retrieval_settings: RetrievalSettings | None = None,
        key_aliases: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        # Path(database_path).resolve()의 반환값을 self._database_path에 대입합니다.
        self._database_path = Path(database_path).resolve(strict=False)
        # Path(data_root).resolve()의 반환값을 self._data_root에 대입합니다.
        self._data_root = Path(data_root).resolve(strict=False)
        # self._inside_root()의 반환값을 self._raw_dir에 대입합니다.
        self._raw_dir = self._inside_root(raw_dir, "raw_dir")
        # self._inside_root()의 반환값을 self._quarantine_dir에 대입합니다.
        self._quarantine_dir = self._inside_root(quarantine_dir, "quarantine_dir")
        # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
        self._raw_dir.mkdir(parents=True, exist_ok=True)
        # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
        self._quarantine_dir.mkdir(parents=True, exist_ok=True)
        # 오른쪽 식을 계산한 값을 self._fsync_raw에 대입합니다.
        self._fsync_raw = fsync_raw
        # 오른쪽 식을 계산한 값을 self._export_dir에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        self._export_dir = (
            Path(export_dir).resolve(strict=False) if export_dir is not None else None
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._export_dir is not None.
        if self._export_dir is not None:
            # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
            self._export_dir.mkdir(parents=True, exist_ok=True)
        # 오른쪽 식을 계산한 값을 self._retrieval_settings에 대입합니다.
        self._retrieval_settings = retrieval_settings
        # dict()의 반환값을 self._key_aliases에 대입합니다.
        self._key_aliases = dict(key_aliases or {})
        # RLock()의 반환값을 self._lock에 대입합니다.
        self._lock = RLock()

    # start_session(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: session_id, started_at.
    # 반환 타입 힌트: SessionRow.
    def start_session(self, session_id: str, started_at: datetime) -> SessionRow:
        # _validate_id()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_id(session_id, "ses")
        # _validate_time()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_time(started_at, "started_at")
        # 오른쪽 식을 계산한 값을 raw_path에 대입합니다.
        raw_path = self._raw_dir / f"{session_id}.jsonl"
        # str()의 반환값을 stored_path에 대입합니다.
        stored_path = str(raw_path.relative_to(self._data_root))
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection, connection:
            # 아래 함수()의 반환값을 existing에 대입합니다.
            existing = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: existing is not None.
            if existing is not None:
                # self._session_from_row()의 반환값을 existing_session에 대입합니다.
                existing_session = self._session_from_row(existing)
                # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
                if (
                    existing_session.started_at != started_at
                    or existing_session.raw_path != raw_path
                ):
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise MemoryCorrupted("기존 세션 ID가 다른 메타데이터와 충돌합니다.")
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return existing_session
            # self._ensure_empty_raw_file()을 호출해 작업을 수행합니다.
            self._ensure_empty_raw_file(raw_path)
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            connection.execute(
                "INSERT INTO sessions(session_id, started_at, raw_path) VALUES (?, ?, ?)",
                (session_id, started_at.isoformat(timespec="milliseconds"), stored_path),
            )
        # self.get_session()의 반환값을 created_session에 대입합니다.
        created_session = self.get_session(session_id)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: created_session is None.
        if created_session is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise MemoryCorrupted("생성한 세션을 다시 읽을 수 없습니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return created_session

    # get_session(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: session_id.
    # 반환 타입 힌트: SessionRow | None.
    def get_session(self, session_id: str) -> SessionRow | None:
        # _validate_id()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_id(session_id, "ses")
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._connection() as connection:
            # 아래 함수()의 반환값을 row에 대입합니다.
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        return None if row is None else self._session_from_row(row)

    # unfinished_sessions(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: list[SessionRow].
    def unfinished_sessions(self) -> list[SessionRow]:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._connection() as connection:
            # 아래 함수()의 반환값을 rows에 대입합니다.
            rows = connection.execute(
                "SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY started_at, session_id"
            ).fetchall()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        return [self._session_from_row(row) for row in rows]

    # append_raw(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: record.
    # 반환 타입 힌트: Path.
    def append_raw(self, record: RawRecord) -> Path:
        # self.get_session()의 반환값을 session에 대입합니다.
        session = self.get_session(record.session_id)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: session is None.
        if session is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise JarvisMemoryError("raw 레코드가 참조하는 세션이 없습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: session.ended_at is not None.
        if session.ended_at is not None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise JarvisMemoryError("종료된 세션에는 raw 레코드를 추가할 수 없습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not session.raw_path.is_file().
        if not session.raw_path.is_file():
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise MemoryCorrupted("세션 raw 로그 파일이 없습니다.")
        # 오른쪽 식을 계산한 값을 payload에 대입합니다.
        payload = (
            json.dumps(
                record.as_dict(),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, session.raw_path.open("ab") as output:
            # 열린 출력 대상에 데이터를 기록합니다.
            output.write(payload)
            # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
            output.flush()
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._fsync_raw.
            if self._fsync_raw:
                # 운영체제에 파일 내용을 저장 장치로 동기화하도록 요청합니다.
                os.fsync(output.fileno())
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return session.raw_path

    # read_raw(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: session_id.
    # 반환 타입 힌트: RawReadResult.
    def read_raw(self, session_id: str) -> RawReadResult:
        # self.get_session()의 반환값을 session에 대입합니다.
        session = self.get_session(session_id)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: session is None.
        if session is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise JarvisMemoryError("raw 로그를 읽을 세션이 없습니다.")
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # session.raw_path.read_bytes()의 반환값을 raw에 대입합니다.
            raw = session.raw_path.read_bytes()
        # OSError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except OSError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise JarvisMemoryError("raw 로그 파일을 읽을 수 없습니다.") from error
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not raw.
        if not raw:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return RawReadResult((), False, None)

        # raw.splitlines()의 반환값을 lines에 대입합니다.
        lines = raw.splitlines(keepends=True)
        # records에 리스트(순서가 있고 수정 가능)을 대입합니다.
        records: list[RawRecord] = []
        # for 반복문: 대상의 항목을 하나씩 (index, line)에 대입하며 아래 블록을 실행합니다.
        for index, line in enumerate(lines):
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # line.rstrip(b'\r\n').decode()의 반환값을 decoded에 대입합니다.
                decoded = line.rstrip(b"\r\n").decode("utf-8")
                # json.loads()의 반환값을 value에 대입합니다.
                value = json.loads(decoded)
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(value, dict).
                if not isinstance(value, dict):
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise ValueError("raw line is not an object")
                # RawRecord.from_mapping()의 반환값을 parsed에 대입합니다.
                parsed = RawRecord.from_mapping(value)
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: parsed.session_id !=
                # session_id.
                if parsed.session_id != session_id:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise MemoryCorrupted(
                        "raw 로그의 session_id가 파일의 세션과 다릅니다.",
                        {"session_id": session_id, "line": index + 1},
                    )
                # 리스트 끝에 항목 하나를 추가합니다.
                records.append(parsed)
            # (UnicodeError, json.JSONDecodeError, TypeError, ValueError)를 잡아 처리합니다. as
            # 뒤의 이름에는
            # 발생한 예외 객체가 담깁니다.
            except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: index != len(lines) - 1.
                if index != len(lines) - 1:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise MemoryCorrupted(
                        "raw 로그 중간에 손상된 줄이 있습니다.",
                        {"session_id": session_id, "line": index + 1},
                    ) from error
                # b''.join()의 반환값을 broken에 대입합니다.
                broken = b"".join(lines[index:])
                # self._next_quarantine_path()의 반환값을 quarantine_path에 대입합니다.
                quarantine_path = self._next_quarantine_path(session_id)
                # write_atomic()을 호출해 작업을 수행합니다.
                write_atomic(quarantine_path, broken)
                # write_atomic()을 호출해 작업을 수행합니다.
                write_atomic(session.raw_path, b"".join(lines[:index]))
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return RawReadResult(tuple(records), True, quarantine_path)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return RawReadResult(tuple(records), False, None)

    # record_turn(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: session_id, usage.
    # 반환 타입 힌트: SessionRow.
    def record_turn(self, session_id: str, usage: LLMUsage) -> SessionRow:
        # _validate_id()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_id(session_id, "ses")
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection, connection:
            # 아래 함수()의 반환값을 row에 대입합니다.
            row = connection.execute(
                "SELECT ended_at, cost_usd FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: row is None.
            if row is None:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise JarvisMemoryError("사용량을 기록할 세션이 없습니다.")
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: row['ended_at'] is not None.
            if row["ended_at"] is not None:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise JarvisMemoryError("종료된 세션에는 사용량을 기록할 수 없습니다.")
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # 오른쪽 식을 계산한 값을 cost에 대입합니다.
                cost = Decimal(str(row["cost_usd"])) + usage.cost_usd
            # InvalidOperation를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
            except InvalidOperation as error:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise MemoryCorrupted("세션 비용 값이 손상되었습니다.") from error
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            connection.execute(
                """
                    UPDATE sessions
                    SET turn_count = turn_count + 1,
                        cost_usd = ?,
                        tokens_in = tokens_in + ?,
                        tokens_out = tokens_out + ?
                    WHERE session_id = ?
                    """,
                (
                    format(cost, "f"),
                    usage.prompt_tokens,
                    usage.completion_tokens,
                    session_id,
                ),
            )
        # self.get_session()의 반환값을 updated에 대입합니다.
        updated = self.get_session(session_id)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: updated is None.
        if updated is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise MemoryCorrupted("갱신한 세션을 다시 읽을 수 없습니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return updated

    # checkpoint(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: session_id, seq, created_at, last_turn_id, turn_count, history_digest.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def checkpoint(
        self,
        session_id: str,
        *,
        seq: int,
        created_at: datetime,
        last_turn_id: str,
        turn_count: int,
        history_digest: str | None = None,
    ) -> None:
        # _validate_id()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_id(session_id, "ses")
        # _validate_id()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_id(last_turn_id, "turn")
        # _validate_time()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_time(created_at, "created_at")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: seq <= 0 or turn_count < 0.
        if seq <= 0 or turn_count < 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("checkpoint seq와 turn_count가 올바르지 않습니다")
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection, connection:
            # 아래 함수()의 반환값을 existing에 대입합니다.
            existing = connection.execute(
                "SELECT * FROM session_checkpoints WHERE session_id = ? AND seq = ?",
                (session_id, seq),
            ).fetchone()
            # values에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
            values = (
                session_id,
                seq,
                created_at.isoformat(timespec="milliseconds"),
                last_turn_id,
                turn_count,
                history_digest,
            )
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: existing is None.
            if existing is None:
                # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
                connection.execute(
                    """
                        INSERT INTO session_checkpoints(
                            session_id, seq, created_at, last_turn_id, turn_count, history_digest
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                    values,
                )
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tuple(existing) != values.
            elif tuple(existing) != values:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise MemoryCorrupted("같은 checkpoint seq가 다른 내용과 충돌합니다.")

    # end_session(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: session_id, ended_at, reason.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: SessionRow.
    def end_session(
        self,
        session_id: str,
        *,
        ended_at: datetime,
        reason: EndReason,
    ) -> SessionRow:
        # _validate_id()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_id(session_id, "ses")
        # _validate_time()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_time(ended_at, "ended_at")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: reason not in {'bye',
        # 'crash_recovered', 'discarded',
        # 'timeout'}.
        if reason not in {"bye", "crash_recovered", "discarded", "timeout"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("세션 종료 사유가 올바르지 않습니다")
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection, connection:
            # 아래 함수()의 반환값을 row에 대입합니다.
            row = connection.execute(
                "SELECT started_at, ended_at FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: row is None.
            if row is None:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise JarvisMemoryError("종료할 세션이 없습니다.")
            # datetime.fromisoformat()의 반환값을 started_at에 대입합니다.
            started_at = datetime.fromisoformat(str(row["started_at"]))
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ended_at < started_at.
            if ended_at < started_at:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise ValueError("ended_at은 세션 시작 시각보다 빠를 수 없습니다")
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: row['ended_at'] is None.
            if row["ended_at"] is None:
                # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
                connection.execute(
                    "UPDATE sessions SET ended_at = ?, end_reason = ? WHERE session_id = ?",
                    (ended_at.isoformat(timespec="milliseconds"), reason, session_id),
                )
        # self.get_session()의 반환값을 ended에 대입합니다.
        ended = self.get_session(session_id)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ended is None.
        if ended is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise MemoryCorrupted("종료한 세션을 다시 읽을 수 없습니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ended

    # put_record(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: rec.
    # 반환 타입 힌트: 문자열(str).
    def put_record(self, rec: MemoryRecord) -> str:
        # self.get_record()의 반환값을 existing에 대입합니다.
        existing = self.get_record(rec.id)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: existing is not None.
        if existing is not None:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return rec.id
        # self._record_insert_values()의 반환값을 values에 대입합니다.
        values = self._record_insert_values(rec)
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection, connection:
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
                connection.execute(
                    """
                    INSERT INTO records(
                        id, schema_version, kind, key, value, status,
                        source_session_id, source_turn_id, source_kind,
                        created_at, updated_at, expires_at, sensitivity,
                        supersedes, tags, deleted_at, delete_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            # sqlite3.IntegrityError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
            # 담깁니다.
            except sqlite3.IntegrityError as error:
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: rec.status == 'confirmed' and
                # rec.key is not None.
                if rec.status == "confirmed" and rec.key is not None:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise JarvisMemoryError(
                        "같은 key에 confirmed 기억이 이미 존재합니다.",
                        {"key": rec.key, "record_id": rec.id},
                    ) from error
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise JarvisMemoryError(
                    "기억 레코드를 저장하지 못했습니다.",
                    {"record_id": rec.id},
                ) from error
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return rec.id

    # get_record(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: record_id.
    # 반환 타입 힌트: MemoryRecord | None.
    def get_record(self, record_id: str) -> MemoryRecord | None:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._connection() as connection:
            # 아래 함수()의 반환값을 row에 대입합니다.
            row = connection.execute(
                "SELECT * FROM records WHERE id = ?", (record_id,)
            ).fetchone()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        return None if row is None else self._row_to_record(row)

    # confirm(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: record_id, at.
    # 반환 타입 힌트: MemoryRecord.
    def confirm(self, record_id: str, at: datetime) -> MemoryRecord:
        # _validate_time()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_time(at, "at")
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection, connection:
            # 아래 함수()의 반환값을 row에 대입합니다.
            row = connection.execute(
                "SELECT * FROM records WHERE id = ?", (record_id,)
            ).fetchone()
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: row is None.
            if row is None:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise JarvisMemoryError(
                    "확정할 기억 레코드를 찾을 수 없습니다.",
                    {"record_id": record_id},
                )
            # self._row_to_record()의 반환값을 current에 대입합니다.
            current = self._row_to_record(row)
            # assert_transition_allowed()을 호출해 작업을 수행합니다.
            assert_transition_allowed(current.status, "confirmed")
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
                connection.execute(
                    """
                    UPDATE records
                    SET status = 'confirmed', updated_at = ?
                    WHERE id = ?
                    """,
                    (at.isoformat(timespec="milliseconds"), record_id),
                )
            # sqlite3.IntegrityError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
            # 담깁니다.
            except sqlite3.IntegrityError as error:
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: current.key is not None.
                if current.key is not None:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise JarvisMemoryError(
                        "같은 key에 confirmed 기억이 이미 존재합니다.",
                        {"key": current.key, "record_id": record_id},
                    ) from error
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise JarvisMemoryError(
                    "기억 레코드를 확정하지 못했습니다.",
                    {"record_id": record_id},
                ) from error
        # self.get_record()의 반환값을 confirmed에 대입합니다.
        confirmed = self.get_record(record_id)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: confirmed is None.
        if confirmed is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise MemoryCorrupted("확정한 기억 레코드를 다시 읽을 수 없습니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return confirmed

    # supersede(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: old_id, new_id, at.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def supersede(self, old_id: str, new_id: str, at: datetime) -> None:
        # _validate_time()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_time(at, "at")
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection, connection:
            # 아래 함수()의 반환값을 old_row에 대입합니다.
            old_row = connection.execute(
                "SELECT * FROM records WHERE id = ?", (old_id,)
            ).fetchone()
            # 아래 함수()의 반환값을 new_row에 대입합니다.
            new_row = connection.execute(
                "SELECT * FROM records WHERE id = ?", (new_id,)
            ).fetchone()
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: old_row is None.
            if old_row is None:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise JarvisMemoryError(
                    "supersede 대상 기억 레코드를 찾을 수 없습니다.",
                    {"record_id": old_id},
                )
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: new_row is None.
            if new_row is None:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise JarvisMemoryError(
                    "supersede 후보 기억 레코드를 찾을 수 없습니다.",
                    {"record_id": new_id},
                )
            # self._row_to_record()의 반환값을 old에 대입합니다.
            old = self._row_to_record(old_row)
            # assert_transition_allowed()을 호출해 작업을 수행합니다.
            assert_transition_allowed(old.status, "superseded")
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            connection.execute(
                """
                UPDATE records
                SET status = 'superseded', updated_at = ?
                WHERE id = ?
                """,
                (at.isoformat(timespec="milliseconds"), old_id),
            )

    # soft_delete(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: record_id, reason, at.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def soft_delete(self, record_id: str, reason: str, at: datetime) -> None:
        # _validate_time()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_time(at, "at")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not reason.strip().
        if not reason.strip():
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("delete_reason은 비어 있을 수 없습니다")
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock, self._connection() as connection, connection:
            # 아래 함수()의 반환값을 row에 대입합니다.
            row = connection.execute(
                "SELECT * FROM records WHERE id = ?", (record_id,)
            ).fetchone()
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: row is None.
            if row is None:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise JarvisMemoryError(
                    "삭제할 기억 레코드를 찾을 수 없습니다.",
                    {"record_id": record_id},
                )
            # self._row_to_record()의 반환값을 current에 대입합니다.
            current = self._row_to_record(row)
            # assert_transition_allowed()을 호출해 작업을 수행합니다.
            assert_transition_allowed(current.status, "deleted")
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            connection.execute(
                """
                UPDATE records
                SET status = 'deleted',
                    deleted_at = ?,
                    delete_reason = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    at.isoformat(timespec="milliseconds"),
                    reason,
                    at.isoformat(timespec="milliseconds"),
                    record_id,
                ),
            )

    # list_records(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: status, kind, limit, offset.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: list[MemoryRecord].
    def list_records(
        self,
        *,
        status: RecordStatus | None = None,
        kind: RecordKind | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: limit < 0 or offset < 0.
        if limit < 0 or offset < 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("limit과 offset은 0 이상이어야 합니다")
        # clauses에 리스트(순서가 있고 수정 가능)을 대입합니다.
        clauses: list[str] = []
        # params에 리스트(순서가 있고 수정 가능)을 대입합니다.
        params: list[Any] = []
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: status is not None.
        if status is not None:
            # 리스트 끝에 항목 하나를 추가합니다.
            clauses.append("status = ?")
            # 리스트 끝에 항목 하나를 추가합니다.
            params.append(status)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: kind is not None.
        if kind is not None:
            # 리스트 끝에 항목 하나를 추가합니다.
            clauses.append("kind = ?")
            # 리스트 끝에 항목 하나를 추가합니다.
            params.append(kind)
        # 오른쪽 식을 계산한 값을 where에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        # 오른쪽 식을 계산한 값을 query에 대입합니다.
        # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
        query = f"""
            SELECT * FROM records
            {where}
            ORDER BY updated_at DESC, id DESC
            LIMIT ? OFFSET ?
        """
        # 반복 가능한 값의 항목들을 리스트 끝에 차례로 추가합니다.
        params.extend([limit, offset])
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._connection() as connection:
            # connection.execute(query, params).fetchall()의 반환값을 rows에 대입합니다.
            rows = connection.execute(query, params).fetchall()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        return [self._row_to_record(row) for row in rows]

    # search(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: q.
    # 반환 타입 힌트: MemorySearchResult.
    def search(self, q: MemoryQuery) -> MemorySearchResult:
        # 오른쪽 식을 계산한 값을 now에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        now = q.now if q.now is not None else datetime.now().astimezone()
        # _validate_time()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_time(now, "now")
        # 오른쪽 식을 계산한 값을 settings에 대입합니다.
        settings = self._retrieval_settings
        # float()의 반환값을 min_score에 대입합니다.
        min_score = float(getattr(settings, "min_score", 0.15) if settings else 0.15)
        # int()의 반환값을 max_candidates에 대입합니다.
        max_candidates = int(getattr(settings, "max_candidates", 3) if settings else 3)
        # 오른쪽 식을 계산한 값을 kind_weights에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        kind_weights = getattr(settings, "kind_weights", {}) if settings else {}
        # 오른쪽 식을 계산한 값을 half_life_days에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        half_life_days = getattr(settings, "half_life_days", {}) if settings else {}

        # tuple()의 반환값을 search_statuses에 대입합니다.
        search_statuses: tuple[RecordStatus, ...] = tuple(
            status for status in q.statuses if status not in {"deleted", "superseded"}
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not search_statuses and (not
        # q.include_candidates).
        if not search_statuses and not q.include_candidates:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return MemorySearchResult((), ())

        # confirmed_scored에 리스트(순서가 있고 수정 가능)을 대입합니다.
        confirmed_scored: list[ScoredRecord] = []
        # candidate_scored에 리스트(순서가 있고 수정 가능)을 대입합니다.
        candidate_scored: list[ScoredRecord] = []
        # set()의 반환값을 seen에 대입합니다.
        seen: set[str] = set()

        # add_scored(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # 입력: item.
        # 반환 타입 힌트: 별도 결과 없음(None).
        def add_scored(item: ScoredRecord) -> None:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: item.record.id in seen.
            if item.record.id in seen:
                # 이 함수를 여기서 끝냅니다. 값을 쓰지 않은 return은 None을 반환합니다.
                return
            # add 메서드를 호출해 항목이나 기록을 추가합니다.
            seen.add(item.record.id)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: item.record.status == 'candidate'.
            if item.record.status == "candidate":
                # 리스트 끝에 항목 하나를 추가합니다.
                candidate_scored.append(item)
            # 앞선 조건이 거짓이면 이 블록을 실행합니다.
            else:
                # 리스트 끝에 항목 하나를 추가합니다.
                confirmed_scored.append(item)

        # extract_key_candidates()의 반환값을 key_candidates에 대입합니다.
        key_candidates = extract_key_candidates(q.text, self._key_aliases)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: key_candidates.
        if key_candidates:
            # ', '.join()의 반환값을 placeholders에 대입합니다.
            placeholders = ", ".join("?" for _ in key_candidates)
            # ', '.join()의 반환값을 status_placeholders에 대입합니다.
            status_placeholders = ", ".join("?" for _ in search_statuses)
            # ', '.join()의 반환값을 kind_placeholders에 대입합니다.
            kind_placeholders = ", ".join("?" for _ in q.kinds)
            # params에 리스트(순서가 있고 수정 가능)을 대입합니다.
            params: list[Any] = [
                *key_candidates,
                *search_statuses,
                *q.kinds,
            ]
            # 오른쪽 식을 계산한 값을 query에 대입합니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            query = f"""
                SELECT * FROM records
                WHERE key IN ({placeholders})
                  AND status IN ({status_placeholders})
                  AND kind IN ({kind_placeholders})
            """
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with self._connection() as connection:
                # connection.execute(query, params).fetchall()의 반환값을 rows에 대입합니다.
                rows = connection.execute(query, params).fetchall()
            # for 반복문: 대상의 항목을 하나씩 row에 대입하며 아래 블록을 실행합니다.
            for row in rows:
                # self._row_to_record()의 반환값을 record에 대입합니다.
                record = self._row_to_record(row)
                # add_scored()을 호출해 작업을 수행합니다.
                add_scored(
                    score_record(
                        record,
                        relevance=1.0,
                        matched_on="key_exact",
                        now=now,
                        kind_weights=kind_weights,
                        half_life_days=half_life_days,
                    )
                )

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: q.include_candidates and 'candidate'
        # not in
        # search_statuses.
        if q.include_candidates and "candidate" not in search_statuses:
            # candidate_statuses에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
            candidate_statuses: tuple[RecordStatus, ...] = ("candidate",)
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # candidate_statuses에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
            candidate_statuses = ()

        # fts_match_query()의 반환값을 fts_query에 대입합니다.
        fts_query = fts_match_query(q.text)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: fts_query.
        if fts_query:
            # for 반복문: 대상의 항목을 하나씩 statuses에 대입하며 아래 블록을 실행합니다.
            for statuses in (search_statuses, candidate_statuses):
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not statuses.
                if not statuses:
                    # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                    continue
                # ', '.join()의 반환값을 status_placeholders에 대입합니다.
                status_placeholders = ", ".join("?" for _ in statuses)
                # ', '.join()의 반환값을 kind_placeholders에 대입합니다.
                kind_placeholders = ", ".join("?" for _ in q.kinds)
                # params에 리스트(순서가 있고 수정 가능)을 대입합니다.
                params = [fts_query, *statuses, *q.kinds]
                # 오른쪽 식을 계산한 값을 sql에 대입합니다.
                # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
                sql = f"""
                    SELECT r.*, bm25(records_fts) AS bm25_rank
                    FROM records_fts
                    JOIN records r ON r.rowid = records_fts.rowid
                    WHERE records_fts MATCH ?
                      AND r.status IN ({status_placeholders})
                      AND r.kind IN ({kind_placeholders})
                    ORDER BY bm25_rank
                    LIMIT 40
                """
                # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
                # 사용합니다.
                with self._connection() as connection:
                    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를
                    # 처리합니다.
                    try:
                        # connection.execute(sql, params).fetchall()의 반환값을 rows에 대입합니다.
                        rows = connection.execute(sql, params).fetchall()
                    # sqlite3.OperationalError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외
                    # 객체가 담깁니다.
                    except sqlite3.OperationalError:
                        # 오른쪽 식을 계산한 값을 sql에 대입합니다.
                        # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
                        sql = f"""
                            SELECT r.*, 0.0 AS bm25_rank
                            FROM records_fts
                            JOIN records r ON r.rowid = records_fts.rowid
                            WHERE records_fts MATCH ?
                              AND r.status IN ({status_placeholders})
                              AND r.kind IN ({kind_placeholders})
                            LIMIT 40
                        """
                        # connection.execute(sql, params).fetchall()의 반환값을 rows에 대입합니다.
                        rows = connection.execute(sql, params).fetchall()
                # for 반복문: 대상의 항목을 하나씩 row에 대입하며 아래 블록을 실행합니다.
                for row in rows:
                    # self._row_to_record()의 반환값을 record에 대입합니다.
                    record = self._row_to_record(row)
                    # 오른쪽 식을 계산한 값을 raw_rank에 대입합니다.
                    raw_rank = row["bm25_rank"]
                    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를
                    # 처리합니다.
                    try:
                        # 오른쪽 식을 계산한 값을 relevance에 대입합니다.
                        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을
                        # 고릅니다.
                        relevance = (
                            normalize_bm25(float(raw_rank))
                            if raw_rank is not None
                            else 1.0
                        )
                    # (TypeError, ValueError)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외
                    # 객체가 담깁니다.
                    except (TypeError, ValueError):
                        # relevance에 숫자 등 고정된 값을 대입합니다.
                        relevance = 1.0
                    # add_scored()을 호출해 작업을 수행합니다.
                    add_scored(
                        score_record(
                            record,
                            relevance=relevance,
                            matched_on="fts",
                            now=now,
                            kind_weights=kind_weights,
                            half_life_days=half_life_days,
                        )
                    )

        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return finalize_search(
            confirmed_scored,
            candidate_scored,
            top_k=q.top_k,
            min_score=min_score,
            max_candidates=max_candidates if q.include_candidates else 0,
        )

    # export(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: dest, include_raw.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: Path.
    def export(self, dest: Path, *, include_raw: bool) -> Path:
        # Path()의 반환값을 target에 대입합니다.
        target = Path(dest)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: target.is_dir() or not target.suffix.
        if target.is_dir() or not target.suffix:
            # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
            target.mkdir(parents=True, exist_ok=True)
            # 오른쪽 식을 계산한 값을 export_file에 대입합니다.
            export_file = target / "records.jsonl"
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
            target.parent.mkdir(parents=True, exist_ok=True)
            # 오른쪽 식을 계산한 값을 export_file에 대입합니다.
            export_file = target

        # self.list_records()의 반환값을 records에 대입합니다.
        records = self.list_records(limit=1_000_000, offset=0)
        # 오른쪽 식을 계산한 값을 lines에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        lines = [
            json.dumps(
                self._record_to_export_dict(record),
                ensure_ascii=False,
                allow_nan=False,
            )
            for record in records
            if record.status != "deleted"
        ]
        # 아래 함수()의 반환값을 payload에 대입합니다.
        payload = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        # write_atomic()을 호출해 작업을 수행합니다.
        write_atomic(export_file, payload)

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: include_raw.
        if include_raw:
            # 오른쪽 식을 계산한 값을 raw_dest에 대입합니다.
            raw_dest = export_file.parent / "raw"
            # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
            raw_dest.mkdir(parents=True, exist_ok=True)
            # for 반복문: 대상의 항목을 하나씩 raw_file에 대입하며 아래 블록을 실행합니다.
            for raw_file in self._raw_dir.glob("*.jsonl"):
                # shutil.copy2()을 호출해 작업을 수행합니다.
                shutil.copy2(raw_file, raw_dest / raw_file.name)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return export_file

    # usage_bytes(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 정수(int).
    def usage_bytes(self) -> int:
        # total에 숫자 등 고정된 값을 대입합니다.
        total = 0
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._database_path.is_file().
        if self._database_path.is_file():
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            total += self._database_path.stat().st_size
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._raw_dir.is_dir().
        if self._raw_dir.is_dir():
            # for 반복문: 대상의 항목을 하나씩 path에 대입하며 아래 블록을 실행합니다.
            for path in self._raw_dir.rglob("*"):
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: path.is_file().
                if path.is_file():
                    # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                    total += path.stat().st_size
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return total

    # integrity_check(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: list[str].
    def integrity_check(self) -> list[str]:
        # problems에 리스트(순서가 있고 수정 가능)을 대입합니다.
        problems: list[str] = []
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with self._connection() as connection:
                # str()의 반환값을 integrity에 대입합니다.
                integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: integrity != 'ok'.
                if integrity != "ok":
                    # 리스트 끝에 항목 하나를 추가합니다.
                    problems.append(f"pragma integrity_check: {integrity}")
                # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를
                # 처리합니다.
                try:
                    # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할
                    # 값입니다.
                    connection.execute(
                        "INSERT INTO records_fts(records_fts) VALUES('integrity-check')"
                    )
                # sqlite3.Error를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
                except sqlite3.Error as error:
                    # 리스트 끝에 항목 하나를 추가합니다.
                    problems.append(f"records_fts integrity-check: {error}")
                # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를
                # 처리합니다.
                try:
                    # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할
                    # 값입니다.
                    connection.execute(
                        "INSERT INTO doc_chunks_fts(doc_chunks_fts) VALUES('integrity-check')"
                    )
                # sqlite3.Error를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
                except sqlite3.Error as error:
                    # 리스트 끝에 항목 하나를 추가합니다.
                    problems.append(f"doc_chunks_fts integrity-check: {error}")
        # JarvisMemoryError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except JarvisMemoryError as error:
            # 리스트 끝에 항목 하나를 추가합니다.
            problems.append(str(error.user_message))
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return problems

    # _record_insert_values(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: rec.
    # 반환 타입 힌트: tuple[Any, ...].
    def _record_insert_values(self, rec: MemoryRecord) -> tuple[Any, ...]:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return (
            rec.id,
            rec.schema_version,
            rec.kind,
            rec.key,
            rec.value,
            rec.status,
            rec.source_session_id,
            rec.source_turn_id,
            rec.source_kind,
            rec.created_at.isoformat(timespec="milliseconds"),
            rec.updated_at.isoformat(timespec="milliseconds"),
            None
            if rec.expires_at is None
            else rec.expires_at.isoformat(timespec="milliseconds"),
            rec.sensitivity,
            rec.supersedes,
            json.dumps(list(rec.tags), ensure_ascii=False),
            None
            if rec.deleted_at is None
            else rec.deleted_at.isoformat(timespec="milliseconds"),
            rec.delete_reason,
        )

    # _row_to_record(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: row.
    # 반환 타입 힌트: MemoryRecord.
    def _row_to_record(self, row: sqlite3.Row) -> MemoryRecord:
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # json.loads()의 반환값을 tags_raw에 대입합니다.
            tags_raw = json.loads(str(row["tags"]))
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(tags_raw, list).
            if not isinstance(tags_raw, list):
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise ValueError("tags must be a JSON array")
            # tuple()의 반환값을 tags에 대입합니다.
            tags = tuple(str(item) for item in tags_raw)
            # 오른쪽 식을 계산한 값을 source_session_id에 대입합니다.
            source_session_id = row["source_session_id"]
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: source_session_id is None.
            if source_session_id is None:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise MemoryCorrupted("기억 레코드 source_session_id가 없습니다.")
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return MemoryRecord(
                id=str(row["id"]),
                schema_version=int(row["schema_version"]),
                kind=cast(RecordKind, row["kind"]),
                key=cast(str | None, row["key"]),
                value=str(row["value"]),
                status=cast(RecordStatus, row["status"]),
                source_session_id=str(source_session_id),
                source_turn_id=cast(str | None, row["source_turn_id"]),
                source_kind=cast(
                    Literal["user_explicit", "summarizer", "import"],
                    row["source_kind"],
                ),
                created_at=datetime.fromisoformat(str(row["created_at"])),
                updated_at=datetime.fromisoformat(str(row["updated_at"])),
                expires_at=None
                if row["expires_at"] is None
                else datetime.fromisoformat(str(row["expires_at"])),
                sensitivity=cast(Literal["normal", "sensitive", "secret"], row["sensitivity"]),
                supersedes=cast(str | None, row["supersedes"]),
                tags=tags,
                deleted_at=None
                if row["deleted_at"] is None
                else datetime.fromisoformat(str(row["deleted_at"])),
                delete_reason=cast(str | None, row["delete_reason"]),
            )
        # (ValueError, TypeError, json.JSONDecodeError)를 잡아 처리합니다. as 뒤의 이름에는 발생한
        # 예외 객체가 담깁니다.
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise MemoryCorrupted("기억 레코드 행의 값이 손상되었습니다.") from error

    # _record_to_export_dict(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: record.
    # 반환 타입 힌트: dict[str, Any].
    def _record_to_export_dict(self, record: MemoryRecord) -> dict[str, Any]:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return {
            "schema_version": record.schema_version,
            "id": record.id,
            "kind": record.kind,
            "key": record.key,
            "value": record.value,
            "status": record.status,
            "source": {
                "session_id": record.source_session_id,
                "turn_id": record.source_turn_id,
                "kind": record.source_kind,
            },
            "created_at": record.created_at.isoformat(timespec="milliseconds"),
            "updated_at": record.updated_at.isoformat(timespec="milliseconds"),
            "expires_at": None
            if record.expires_at is None
            else record.expires_at.isoformat(timespec="milliseconds"),
            "sensitivity": record.sensitivity,
            "supersedes": record.supersedes,
            "tags": list(record.tags),
        }

    # _connection(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Iterator[sqlite3.Connection].
    # @contextmanager: yield 앞은 with 진입 준비, 뒤는 with 종료 시 처리입니다.
    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with closing(sqlite3.connect(self._database_path)) as connection:
                # 오른쪽 식을 계산한 값을 connection.row_factory에 대입합니다.
                connection.row_factory = sqlite3.Row
                # configure_connection()을 호출해 작업을 수행합니다.
                configure_connection(connection)
                # yield는 값을 건네고 실행을 잠시 멈춥니다. 다음 요청이 오면 이어서 진행합니다.
                yield connection
        # (JarvisMemoryError, MemoryCorrupted, RecoveryError)를 잡아 처리합니다. as 뒤의 이름에는
        # 발생한 예외 객체가
        # 담깁니다.
        except (JarvisMemoryError, MemoryCorrupted, RecoveryError):
            # 현재 예외를 다시 발생시켜 호출한 쪽으로 전달합니다.
            raise
        # sqlite3.Error를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except sqlite3.Error as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise JarvisMemoryError(
                "세션 데이터베이스 작업에 실패했습니다.",
                {"error_type": type(error).__name__},
            ) from error

    # _session_from_row(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: row.
    # 반환 타입 힌트: SessionRow.
    def _session_from_row(self, row: sqlite3.Row) -> SessionRow:
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # datetime.fromisoformat()의 반환값을 started_at에 대입합니다.
            started_at = datetime.fromisoformat(str(row["started_at"]))
            # 오른쪽 식을 계산한 값을 ended_value에 대입합니다.
            ended_value = row["ended_at"]
            # 오른쪽 식을 계산한 값을 ended_at에 대입합니다.
            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
            ended_at = None if ended_value is None else datetime.fromisoformat(str(ended_value))
            # Decimal()의 반환값을 cost에 대입합니다.
            cost = Decimal(str(row["cost_usd"]))
            # self._stored_raw_path()의 반환값을 raw_path에 대입합니다.
            raw_path = self._stored_raw_path(str(row["raw_path"]))
        # (ValueError, InvalidOperation)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
        # 담깁니다.
        except (ValueError, InvalidOperation) as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise MemoryCorrupted("세션 행의 값이 손상되었습니다.") from error
        # 오른쪽 식을 계산한 값을 end_reason에 대입합니다.
        end_reason = row["end_reason"]
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if end_reason not in {None, "bye", "crash_recovered", "discarded", "timeout"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise MemoryCorrupted("세션 종료 사유가 손상되었습니다.")
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # _validate_id()으로 입력 형식과 허용 조건을 검사합니다.
            _validate_id(str(row["session_id"]), "ses")
            # _validate_time()으로 입력 형식과 허용 조건을 검사합니다.
            _validate_time(started_at, "started_at")
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ended_at is not None.
            if ended_at is not None:
                # _validate_time()으로 입력 형식과 허용 조건을 검사합니다.
                _validate_time(ended_at, "ended_at")
        # ValueError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except ValueError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise MemoryCorrupted("세션 행의 ID 또는 시각이 손상되었습니다.") from error
        # int()의 반환값을 turn_count에 대입합니다.
        turn_count = int(row["turn_count"])
        # int()의 반환값을 tokens_in에 대입합니다.
        tokens_in = int(row["tokens_in"])
        # int()의 반환값을 tokens_out에 대입합니다.
        tokens_out = int(row["tokens_out"])
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if (
            turn_count < 0
            or tokens_in < 0
            or tokens_out < 0
            or not cost.is_finite()
            or cost < 0
            or (ended_at is not None and ended_at < started_at)
        ):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise MemoryCorrupted("세션 행의 누적값이 손상되었습니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return SessionRow(
            session_id=str(row["session_id"]),
            started_at=started_at,
            ended_at=ended_at,
            end_reason=cast(EndReason | None, end_reason),
            turn_count=turn_count,
            raw_path=raw_path,
            cost_usd=cost,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    # _stored_raw_path(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: stored.
    # 반환 타입 힌트: Path.
    def _stored_raw_path(self, stored: str) -> Path:
        # Path()의 반환값을 configured에 대입합니다.
        configured = Path(stored)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: configured.is_absolute().
        if configured.is_absolute():
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise MemoryCorrupted("세션 raw_path는 상대 경로여야 합니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._inside_root(self._data_root / configured, "session.raw_path")

    # _inside_root(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: path, field.
    # 반환 타입 힌트: Path.
    def _inside_root(self, path: Path, field: str) -> Path:
        # Path(path).resolve()의 반환값을 resolved에 대입합니다.
        resolved = Path(path).resolve(strict=False)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not
        # resolved.is_relative_to(self._data_root).
        if not resolved.is_relative_to(self._data_root):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise RecoveryError(
                "세션 저장 경로가 data_root 밖을 가리킵니다.",
                {"field": field, "path": str(resolved)},
            )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return resolved

    # _ensure_empty_raw_file(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: path.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _ensure_empty_raw_file(self, path: Path) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: path.exists().
        if path.exists():
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: path.stat().st_size != 0.
            if path.stat().st_size != 0:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise RecoveryError("DB에 없는 세션 ID의 raw 로그가 이미 존재합니다.")
            # 이 함수를 여기서 끝냅니다. 값을 쓰지 않은 return은 None을 반환합니다.
            return
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with path.open("xb") as output:
            # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
            output.flush()
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._fsync_raw.
            if self._fsync_raw:
                # 운영체제에 파일 내용을 저장 장치로 동기화하도록 요청합니다.
                os.fsync(output.fileno())

    # _next_quarantine_path(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: session_id.
    # 반환 타입 힌트: Path.
    def _next_quarantine_path(self, session_id: str) -> Path:
        # 오른쪽 식을 계산한 값을 base에 대입합니다.
        base = self._quarantine_dir / f"{session_id}.tail"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not base.exists().
        if not base.exists():
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return base
        # suffix에 숫자 등 고정된 값을 대입합니다.
        suffix = 1
        # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
        while (candidate := self._quarantine_dir / f"{session_id}.tail.{suffix}").exists():
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            suffix += 1
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return candidate


# 오른쪽 식을 계산한 값을 SqliteMemoryStore에 대입합니다.
SqliteMemoryStore = SQLiteSessionStore


# _validate_id(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value, prefix.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_id(value: str, prefix: str) -> None:
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if not isinstance(value, str) or re.fullmatch(rf"{prefix}_{_ULID_PATTERN}", value) is None:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError(f"{prefix} ID가 올바르지 않습니다")


# _validate_time(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value, field.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_time(value: datetime, field: str) -> None:
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError(f"{field}는 timezone-aware datetime이어야 합니다")


# _required_string(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value, field.
# 반환 타입 힌트: 문자열(str).
def _required_string(value: Any, field: str) -> str:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(value, str).
    if not isinstance(value, str):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError(f"raw {field}가 올바르지 않습니다")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return value

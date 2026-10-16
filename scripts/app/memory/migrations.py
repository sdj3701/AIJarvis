# 파이썬 공부 | scripts/app/memory/migrations.py
# SQLite 데이터베이스 구조를 만들고 버전을 검사합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Create and verify the versioned SQLite data store."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.clock import SystemClock
from app.core.errors import ConfigError, MemoryCorrupted

# SCHEMA_VERSION에 숫자 등 고정된 값을 대입합니다.
SCHEMA_VERSION = 1
# MIN_SQLITE_VERSION에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
MIN_SQLITE_VERSION = (3, 34, 0)

# frozenset()의 반환값을 REQUIRED_TABLES에 대입합니다.
REQUIRED_TABLES = frozenset(
    {
        "meta",
        "sessions",
        "session_checkpoints",
        "records",
        "records_fts",
        "embeddings",
        "documents",
        "doc_chunks",
        "doc_chunks_fts",
        "tasks",
        "task_steps",
        "approvals",
        "budget_usage",
        "metrics",
    }
)
# frozenset()의 반환값을 REQUIRED_TRIGGERS에 대입합니다.
REQUIRED_TRIGGERS = frozenset(
    {
        "trg_records_ai",
        "trg_records_ad",
        "trg_records_au",
        "trg_records_embedding_cleanup",
        "trg_doc_chunks_ai",
        "trg_doc_chunks_ad",
        "trg_doc_chunks_au",
    }
)


# DatabaseInitResult: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class DatabaseInitResult:
    """Outcome of an idempotent database initialization."""

    # path: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    path: Path
    # created: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    created: bool
    # schema_version: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    schema_version: int


# _schema_sql(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: 문자열(str).
def _schema_sql() -> str:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


# _version_text(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: version.
# 반환 타입 힌트: 문자열(str).
def _version_text(version: tuple[int, int, int]) -> str:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return ".".join(str(part) for part in version)


# _check_sqlite_version(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: version.
# 반환 타입 힌트: 별도 결과 없음(None).
def _check_sqlite_version(version: tuple[int, int, int]) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: version < MIN_SQLITE_VERSION.
    if version < MIN_SQLITE_VERSION:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            "SQLite 3.34 이상이 필요합니다.",
            {
                "required": _version_text(MIN_SQLITE_VERSION),
                "actual": _version_text(version),
            },
        )


# configure_connection(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: connection.
# 반환 타입 힌트: 별도 결과 없음(None).
def configure_connection(connection: sqlite3.Connection) -> None:
    """Apply the durability and referential-integrity pragmas from DESIGN.md."""
    # 오른쪽 식을 계산한 값을 journal_mode에 대입합니다.
    journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: str(journal_mode).lower() != 'wal'.
    if str(journal_mode).lower() != "wal":
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            "SQLite WAL 모드를 활성화하지 못했습니다.",
            {"journal_mode": str(journal_mode)},
        )
    # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
    connection.execute("PRAGMA synchronous = FULL")
    # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
    connection.execute("PRAGMA foreign_keys = ON")
    # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
    connection.execute("PRAGMA busy_timeout = 5000")


# _current_schema_version(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: connection.
# 반환 타입 힌트: 정수(int).
def _current_schema_version(connection: sqlite3.Connection) -> int:
    # 아래 함수()의 반환값을 has_meta에 대입합니다.
    has_meta = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: has_meta is None.
    if has_meta is None:
        # 0을 반환하고 이 함수의 실행을 끝냅니다.
        return 0
    # 아래 함수()의 반환값을 row에 대입합니다.
    row = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: row is None.
    if row is None:
        # 0을 반환하고 이 함수의 실행을 끝냅니다.
        return 0
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return int(row[0])
    # (TypeError, ValueError)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except (TypeError, ValueError) as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError("SQLite schema_version 값이 올바르지 않습니다.") from error


# _apply_v1(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: connection, created_at.
# 반환 타입 힌트: 별도 결과 없음(None).
def _apply_v1(connection: sqlite3.Connection, created_at: datetime) -> None:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # connection.executescript()을 호출해 작업을 수행합니다.
        connection.executescript("BEGIN IMMEDIATE;\n" + _schema_sql())
        # connection.executemany()을 호출해 작업을 수행합니다.
        connection.executemany(
            "INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)",
            (
                ("schema_version", str(SCHEMA_VERSION)),
                ("audit_seq", "0"),
                ("created_at", created_at.isoformat(timespec="milliseconds")),
            ),
        )
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute("COMMIT")
    # sqlite3.Error를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except sqlite3.Error:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: connection.in_transaction.
        if connection.in_transaction:
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            connection.execute("ROLLBACK")
        # 현재 예외를 다시 발생시켜 호출한 쪽으로 전달합니다.
        raise


# verify_schema(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: connection.
# 반환 타입 힌트: 별도 결과 없음(None).
def verify_schema(connection: sqlite3.Connection) -> None:
    """Verify all documented tables, triggers, and SQLite integrity checks."""
    # 오른쪽 식을 계산한 값을 tables에 대입합니다.
    # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    # 오른쪽 식을 계산한 값을 triggers에 대입합니다.
    # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
    triggers = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
    }
    # sorted()의 반환값을 missing_tables에 대입합니다.
    missing_tables = sorted(REQUIRED_TABLES - tables)
    # sorted()의 반환값을 missing_triggers에 대입합니다.
    missing_triggers = sorted(REQUIRED_TRIGGERS - triggers)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: missing_tables or missing_triggers.
    if missing_tables or missing_triggers:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise MemoryCorrupted(
            "SQLite 스키마 구성 요소가 누락되었습니다.",
            {"missing_tables": missing_tables, "missing_triggers": missing_triggers},
        )

    # str()의 반환값을 integrity에 대입합니다.
    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: integrity != 'ok'.
    if integrity != "ok":
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise MemoryCorrupted("SQLite 무결성 검사에 실패했습니다.", {"integrity": integrity})
    # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
    connection.execute("INSERT INTO records_fts(records_fts) VALUES('integrity-check')")
    # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
    connection.execute("INSERT INTO doc_chunks_fts(doc_chunks_fts) VALUES('integrity-check')")


# initialize_database(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: database_path, created_at, sqlite_version_info.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: DatabaseInitResult.
def initialize_database(
    database_path: Path,
    *,
    created_at: datetime | None = None,
    sqlite_version_info: tuple[int, int, int] | None = None,
) -> DatabaseInitResult:
    """Initialize schema version 1 without modifying an existing valid database."""
    # 오른쪽 식을 계산한 값을 version에 대입합니다.
    version = sqlite_version_info or sqlite3.sqlite_version_info
    # _check_sqlite_version()을 호출해 작업을 수행합니다.
    _check_sqlite_version(version)
    # database_path.exists()의 반환값을 existed에 대입합니다.
    existed = database_path.exists()
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    database_path.parent.mkdir(parents=True, exist_ok=True)

    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with closing(sqlite3.connect(database_path, isolation_level=None)) as connection:
            # configure_connection()을 호출해 작업을 수행합니다.
            configure_connection(connection)
            # _current_schema_version()의 반환값을 current에 대입합니다.
            current = _current_schema_version(connection)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: current > SCHEMA_VERSION.
            if current > SCHEMA_VERSION:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise ConfigError(
                    "데이터베이스가 이 앱보다 새로운 스키마를 사용합니다.",
                    {"supported": SCHEMA_VERSION, "actual": current},
                )
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: current < SCHEMA_VERSION.
            if current < SCHEMA_VERSION:
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: current != 0.
                if current != 0:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise ConfigError(
                        "지원되지 않는 SQLite 마이그레이션 경로입니다.",
                        {"supported": SCHEMA_VERSION, "actual": current},
                    )
                # _apply_v1()을 호출해 작업을 수행합니다.
                _apply_v1(connection, created_at or SystemClock().now())
            # verify_schema()을 호출해 작업을 수행합니다.
            verify_schema(connection)
    # (ConfigError, MemoryCorrupted)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
    # 담깁니다.
    except (ConfigError, MemoryCorrupted):
        # 현재 예외를 다시 발생시켜 호출한 쪽으로 전달합니다.
        raise
    # sqlite3.Error를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except sqlite3.Error as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            "SQLite 데이터베이스를 초기화하지 못했습니다.",
            {"database": str(database_path), "error_type": type(error).__name__},
        ) from error

    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return DatabaseInitResult(
        path=database_path,
        created=not existed,
        schema_version=SCHEMA_VERSION,
    )

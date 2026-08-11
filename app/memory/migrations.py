"""Create and verify the versioned SQLite data store."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.clock import SystemClock
from app.core.errors import ConfigError, MemoryCorrupted

SCHEMA_VERSION = 1
MIN_SQLITE_VERSION = (3, 34, 0)

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


@dataclass(frozen=True, slots=True)
class DatabaseInitResult:
    """Outcome of an idempotent database initialization."""

    path: Path
    created: bool
    schema_version: int


def _schema_sql() -> str:
    return Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


def _version_text(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def _check_sqlite_version(version: tuple[int, int, int]) -> None:
    if version < MIN_SQLITE_VERSION:
        raise ConfigError(
            "SQLite 3.34 이상이 필요합니다.",
            {
                "required": _version_text(MIN_SQLITE_VERSION),
                "actual": _version_text(version),
            },
        )


def configure_connection(connection: sqlite3.Connection) -> None:
    """Apply the durability and referential-integrity pragmas from DESIGN.md."""
    journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    if str(journal_mode).lower() != "wal":
        raise ConfigError(
            "SQLite WAL 모드를 활성화하지 못했습니다.",
            {"journal_mode": str(journal_mode)},
        )
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")


def _current_schema_version(connection: sqlite3.Connection) -> int:
    has_meta = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    if has_meta is None:
        return 0
    row = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError) as error:
        raise ConfigError("SQLite schema_version 값이 올바르지 않습니다.") from error


def _apply_v1(connection: sqlite3.Connection, created_at: datetime) -> None:
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + _schema_sql())
        connection.executemany(
            "INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)",
            (
                ("schema_version", str(SCHEMA_VERSION)),
                ("audit_seq", "0"),
                ("created_at", created_at.isoformat(timespec="milliseconds")),
            ),
        )
        connection.execute("COMMIT")
    except sqlite3.Error:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise


def verify_schema(connection: sqlite3.Connection) -> None:
    """Verify all documented tables, triggers, and SQLite integrity checks."""
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    triggers = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
    }
    missing_tables = sorted(REQUIRED_TABLES - tables)
    missing_triggers = sorted(REQUIRED_TRIGGERS - triggers)
    if missing_tables or missing_triggers:
        raise MemoryCorrupted(
            "SQLite 스키마 구성 요소가 누락되었습니다.",
            {"missing_tables": missing_tables, "missing_triggers": missing_triggers},
        )

    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    if integrity != "ok":
        raise MemoryCorrupted("SQLite 무결성 검사에 실패했습니다.", {"integrity": integrity})
    connection.execute("INSERT INTO records_fts(records_fts) VALUES('integrity-check')")
    connection.execute("INSERT INTO doc_chunks_fts(doc_chunks_fts) VALUES('integrity-check')")


def initialize_database(
    database_path: Path,
    *,
    created_at: datetime | None = None,
    sqlite_version_info: tuple[int, int, int] | None = None,
) -> DatabaseInitResult:
    """Initialize schema version 1 without modifying an existing valid database."""
    version = sqlite_version_info or sqlite3.sqlite_version_info
    _check_sqlite_version(version)
    existed = database_path.exists()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with closing(sqlite3.connect(database_path, isolation_level=None)) as connection:
            configure_connection(connection)
            current = _current_schema_version(connection)
            if current > SCHEMA_VERSION:
                raise ConfigError(
                    "데이터베이스가 이 앱보다 새로운 스키마를 사용합니다.",
                    {"supported": SCHEMA_VERSION, "actual": current},
                )
            if current < SCHEMA_VERSION:
                if current != 0:
                    raise ConfigError(
                        "지원되지 않는 SQLite 마이그레이션 경로입니다.",
                        {"supported": SCHEMA_VERSION, "actual": current},
                    )
                _apply_v1(connection, created_at or SystemClock().now())
            verify_schema(connection)
    except (ConfigError, MemoryCorrupted):
        raise
    except sqlite3.Error as error:
        raise ConfigError(
            "SQLite 데이터베이스를 초기화하지 못했습니다.",
            {"database": str(database_path), "error_type": type(error).__name__},
        ) from error

    return DatabaseInitResult(
        path=database_path,
        created=not existed,
        schema_version=SCHEMA_VERSION,
    )

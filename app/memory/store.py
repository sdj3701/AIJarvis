"""Phase 1 session state and crash-safe raw conversation storage."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock
from typing import Any, Literal, cast

from app.core.atomic import write_atomic
from app.core.errors import MemoryCorrupted, RecoveryError
from app.core.errors import MemoryError as JarvisMemoryError
from app.llm.base import LLMUsage
from app.memory.migrations import configure_connection

RawRole = Literal["user", "assistant", "tool", "system_note"]
Channel = Literal["text", "voice"]
EndReason = Literal["bye", "crash_recovered", "discarded", "timeout"]

_ULID_PATTERN = r"[0-9A-HJKMNP-TV-Z]{26}"
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


@dataclass(frozen=True, slots=True)
class RawRecord:
    ts: datetime
    session_id: str
    turn_id: str
    role: RawRole
    content: str
    channel: Channel
    request_id: str
    tool_call_id: str | None = None
    untrusted: bool = False
    meta: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        _validate_time(self.ts, "ts")
        _validate_id(self.session_id, "ses")
        _validate_id(self.turn_id, "turn")
        _validate_id(self.request_id, "req")
        if self.role not in {"user", "assistant", "tool", "system_note"}:
            raise ValueError("raw role이 올바르지 않습니다")
        if self.channel not in {"text", "voice"}:
            raise ValueError("raw channel이 올바르지 않습니다")
        if not isinstance(self.content, str):
            raise TypeError("raw content는 문자열이어야 합니다")
        if not isinstance(self.untrusted, bool):
            raise TypeError("raw untrusted는 bool이어야 합니다")
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("tool raw 레코드에는 tool_call_id가 필요합니다")
        if self.role != "tool" and self.tool_call_id is not None:
            raise ValueError("tool_call_id는 tool raw 레코드에만 허용됩니다")
        if self.meta is not None and not isinstance(self.meta, Mapping):
            raise TypeError("raw meta는 객체여야 합니다")

    def as_dict(self) -> dict[str, Any]:
        meta = dict(self.meta or {})
        meta["request_id"] = self.request_id
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
        try:
            json.dumps(record, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("raw meta는 JSON으로 직렬화할 수 있어야 합니다") from error
        return record

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RawRecord:
        if set(value) != _RAW_KEYS or value.get("v") != 1:
            raise ValueError("raw 레코드 스키마가 올바르지 않습니다")
        meta = value.get("meta")
        if not isinstance(meta, dict):
            raise ValueError("raw meta가 올바르지 않습니다")
        request_id = meta.get("request_id")
        if not isinstance(request_id, str):
            raise ValueError("raw meta.request_id가 올바르지 않습니다")
        timestamp = value.get("ts")
        if not isinstance(timestamp, str):
            raise ValueError("raw ts가 올바르지 않습니다")
        try:
            parsed_time = datetime.fromisoformat(timestamp)
        except ValueError as error:
            raise ValueError("raw ts가 올바르지 않습니다") from error
        extra_meta = {key: item for key, item in meta.items() if key != "request_id"}
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


@dataclass(frozen=True, slots=True)
class RawReadResult:
    records: tuple[RawRecord, ...]
    broken_tail: bool
    quarantine_path: Path | None


@dataclass(frozen=True, slots=True)
class SessionRow:
    session_id: str
    started_at: datetime
    ended_at: datetime | None
    end_reason: EndReason | None
    turn_count: int
    raw_path: Path
    cost_usd: Decimal
    tokens_in: int
    tokens_out: int


class SQLiteSessionStore:
    """Own session rows and raw JSONL without mixing in Phase 2 memory records."""

    def __init__(
        self,
        database_path: Path,
        *,
        data_root: Path,
        raw_dir: Path,
        quarantine_dir: Path,
        fsync_raw: bool,
    ) -> None:
        self._database_path = Path(database_path).resolve(strict=False)
        self._data_root = Path(data_root).resolve(strict=False)
        self._raw_dir = self._inside_root(raw_dir, "raw_dir")
        self._quarantine_dir = self._inside_root(quarantine_dir, "quarantine_dir")
        self._raw_dir.mkdir(parents=True, exist_ok=True)
        self._quarantine_dir.mkdir(parents=True, exist_ok=True)
        self._fsync_raw = fsync_raw
        self._lock = RLock()

    def start_session(self, session_id: str, started_at: datetime) -> SessionRow:
        _validate_id(session_id, "ses")
        _validate_time(started_at, "started_at")
        raw_path = self._raw_dir / f"{session_id}.jsonl"
        stored_path = str(raw_path.relative_to(self._data_root))
        with self._lock, self._connection() as connection, connection:
            existing = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if existing is not None:
                existing_session = self._session_from_row(existing)
                if (
                    existing_session.started_at != started_at
                    or existing_session.raw_path != raw_path
                ):
                    raise MemoryCorrupted("기존 세션 ID가 다른 메타데이터와 충돌합니다.")
                return existing_session
            self._ensure_empty_raw_file(raw_path)
            connection.execute(
                "INSERT INTO sessions(session_id, started_at, raw_path) VALUES (?, ?, ?)",
                (session_id, started_at.isoformat(timespec="milliseconds"), stored_path),
            )
        created_session = self.get_session(session_id)
        if created_session is None:
            raise MemoryCorrupted("생성한 세션을 다시 읽을 수 없습니다.")
        return created_session

    def get_session(self, session_id: str) -> SessionRow | None:
        _validate_id(session_id, "ses")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return None if row is None else self._session_from_row(row)

    def unfinished_sessions(self) -> list[SessionRow]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY started_at, session_id"
            ).fetchall()
        return [self._session_from_row(row) for row in rows]

    def append_raw(self, record: RawRecord) -> Path:
        session = self.get_session(record.session_id)
        if session is None:
            raise JarvisMemoryError("raw 레코드가 참조하는 세션이 없습니다.")
        if session.ended_at is not None:
            raise JarvisMemoryError("종료된 세션에는 raw 레코드를 추가할 수 없습니다.")
        if not session.raw_path.is_file():
            raise MemoryCorrupted("세션 raw 로그 파일이 없습니다.")
        payload = (
            json.dumps(
                record.as_dict(),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        with self._lock, session.raw_path.open("ab") as output:
            output.write(payload)
            output.flush()
            if self._fsync_raw:
                os.fsync(output.fileno())
        return session.raw_path

    def read_raw(self, session_id: str) -> RawReadResult:
        session = self.get_session(session_id)
        if session is None:
            raise JarvisMemoryError("raw 로그를 읽을 세션이 없습니다.")
        try:
            raw = session.raw_path.read_bytes()
        except OSError as error:
            raise JarvisMemoryError("raw 로그 파일을 읽을 수 없습니다.") from error
        if not raw:
            return RawReadResult((), False, None)

        lines = raw.splitlines(keepends=True)
        records: list[RawRecord] = []
        for index, line in enumerate(lines):
            try:
                decoded = line.rstrip(b"\r\n").decode("utf-8")
                value = json.loads(decoded)
                if not isinstance(value, dict):
                    raise ValueError("raw line is not an object")
                parsed = RawRecord.from_mapping(value)
                if parsed.session_id != session_id:
                    raise MemoryCorrupted(
                        "raw 로그의 session_id가 파일의 세션과 다릅니다.",
                        {"session_id": session_id, "line": index + 1},
                    )
                records.append(parsed)
            except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
                if index != len(lines) - 1:
                    raise MemoryCorrupted(
                        "raw 로그 중간에 손상된 줄이 있습니다.",
                        {"session_id": session_id, "line": index + 1},
                    ) from error
                broken = b"".join(lines[index:])
                quarantine_path = self._next_quarantine_path(session_id)
                write_atomic(quarantine_path, broken)
                write_atomic(session.raw_path, b"".join(lines[:index]))
                return RawReadResult(tuple(records), True, quarantine_path)
        return RawReadResult(tuple(records), False, None)

    def record_turn(self, session_id: str, usage: LLMUsage) -> SessionRow:
        _validate_id(session_id, "ses")
        with self._lock, self._connection() as connection, connection:
            row = connection.execute(
                "SELECT ended_at, cost_usd FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise JarvisMemoryError("사용량을 기록할 세션이 없습니다.")
            if row["ended_at"] is not None:
                raise JarvisMemoryError("종료된 세션에는 사용량을 기록할 수 없습니다.")
            try:
                cost = Decimal(str(row["cost_usd"])) + usage.cost_usd
            except InvalidOperation as error:
                raise MemoryCorrupted("세션 비용 값이 손상되었습니다.") from error
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
        updated = self.get_session(session_id)
        if updated is None:
            raise MemoryCorrupted("갱신한 세션을 다시 읽을 수 없습니다.")
        return updated

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
        _validate_id(session_id, "ses")
        _validate_id(last_turn_id, "turn")
        _validate_time(created_at, "created_at")
        if seq <= 0 or turn_count < 0:
            raise ValueError("checkpoint seq와 turn_count가 올바르지 않습니다")
        with self._lock, self._connection() as connection, connection:
            existing = connection.execute(
                "SELECT * FROM session_checkpoints WHERE session_id = ? AND seq = ?",
                (session_id, seq),
            ).fetchone()
            values = (
                session_id,
                seq,
                created_at.isoformat(timespec="milliseconds"),
                last_turn_id,
                turn_count,
                history_digest,
            )
            if existing is None:
                connection.execute(
                    """
                        INSERT INTO session_checkpoints(
                            session_id, seq, created_at, last_turn_id, turn_count, history_digest
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                    values,
                )
            elif tuple(existing) != values:
                raise MemoryCorrupted("같은 checkpoint seq가 다른 내용과 충돌합니다.")

    def end_session(
        self,
        session_id: str,
        *,
        ended_at: datetime,
        reason: EndReason,
    ) -> SessionRow:
        _validate_id(session_id, "ses")
        _validate_time(ended_at, "ended_at")
        if reason not in {"bye", "crash_recovered", "discarded", "timeout"}:
            raise ValueError("세션 종료 사유가 올바르지 않습니다")
        with self._lock, self._connection() as connection, connection:
            row = connection.execute(
                "SELECT started_at, ended_at FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise JarvisMemoryError("종료할 세션이 없습니다.")
            started_at = datetime.fromisoformat(str(row["started_at"]))
            if ended_at < started_at:
                raise ValueError("ended_at은 세션 시작 시각보다 빠를 수 없습니다")
            if row["ended_at"] is None:
                connection.execute(
                    "UPDATE sessions SET ended_at = ?, end_reason = ? WHERE session_id = ?",
                    (ended_at.isoformat(timespec="milliseconds"), reason, session_id),
                )
        ended = self.get_session(session_id)
        if ended is None:
            raise MemoryCorrupted("종료한 세션을 다시 읽을 수 없습니다.")
        return ended

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            with closing(sqlite3.connect(self._database_path)) as connection:
                connection.row_factory = sqlite3.Row
                configure_connection(connection)
                yield connection
        except (JarvisMemoryError, MemoryCorrupted, RecoveryError):
            raise
        except sqlite3.Error as error:
            raise JarvisMemoryError(
                "세션 데이터베이스 작업에 실패했습니다.",
                {"error_type": type(error).__name__},
            ) from error

    def _session_from_row(self, row: sqlite3.Row) -> SessionRow:
        try:
            started_at = datetime.fromisoformat(str(row["started_at"]))
            ended_value = row["ended_at"]
            ended_at = None if ended_value is None else datetime.fromisoformat(str(ended_value))
            cost = Decimal(str(row["cost_usd"]))
            raw_path = self._stored_raw_path(str(row["raw_path"]))
        except (ValueError, InvalidOperation) as error:
            raise MemoryCorrupted("세션 행의 값이 손상되었습니다.") from error
        end_reason = row["end_reason"]
        if end_reason not in {None, "bye", "crash_recovered", "discarded", "timeout"}:
            raise MemoryCorrupted("세션 종료 사유가 손상되었습니다.")
        try:
            _validate_id(str(row["session_id"]), "ses")
            _validate_time(started_at, "started_at")
            if ended_at is not None:
                _validate_time(ended_at, "ended_at")
        except ValueError as error:
            raise MemoryCorrupted("세션 행의 ID 또는 시각이 손상되었습니다.") from error
        turn_count = int(row["turn_count"])
        tokens_in = int(row["tokens_in"])
        tokens_out = int(row["tokens_out"])
        if (
            turn_count < 0
            or tokens_in < 0
            or tokens_out < 0
            or not cost.is_finite()
            or cost < 0
            or (ended_at is not None and ended_at < started_at)
        ):
            raise MemoryCorrupted("세션 행의 누적값이 손상되었습니다.")
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

    def _stored_raw_path(self, stored: str) -> Path:
        configured = Path(stored)
        if configured.is_absolute():
            raise MemoryCorrupted("세션 raw_path는 상대 경로여야 합니다.")
        return self._inside_root(self._data_root / configured, "session.raw_path")

    def _inside_root(self, path: Path, field: str) -> Path:
        resolved = Path(path).resolve(strict=False)
        if not resolved.is_relative_to(self._data_root):
            raise RecoveryError(
                "세션 저장 경로가 data_root 밖을 가리킵니다.",
                {"field": field, "path": str(resolved)},
            )
        return resolved

    def _ensure_empty_raw_file(self, path: Path) -> None:
        if path.exists():
            if path.stat().st_size != 0:
                raise RecoveryError("DB에 없는 세션 ID의 raw 로그가 이미 존재합니다.")
            return
        with path.open("xb") as output:
            output.flush()
            if self._fsync_raw:
                os.fsync(output.fileno())

    def _next_quarantine_path(self, session_id: str) -> Path:
        base = self._quarantine_dir / f"{session_id}.tail"
        if not base.exists():
            return base
        suffix = 1
        while (candidate := self._quarantine_dir / f"{session_id}.tail.{suffix}").exists():
            suffix += 1
        return candidate


def _validate_id(value: str, prefix: str) -> None:
    if not isinstance(value, str) or re.fullmatch(rf"{prefix}_{_ULID_PATTERN}", value) is None:
        raise ValueError(f"{prefix} ID가 올바르지 않습니다")


def _validate_time(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field}는 timezone-aware datetime이어야 합니다")


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"raw {field}가 올바르지 않습니다")
    return value

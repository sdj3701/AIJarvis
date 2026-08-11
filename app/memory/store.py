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
    """Session rows, raw JSONL, and Phase 2 memory records in one SQLite store."""

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
        self._database_path = Path(database_path).resolve(strict=False)
        self._data_root = Path(data_root).resolve(strict=False)
        self._raw_dir = self._inside_root(raw_dir, "raw_dir")
        self._quarantine_dir = self._inside_root(quarantine_dir, "quarantine_dir")
        self._raw_dir.mkdir(parents=True, exist_ok=True)
        self._quarantine_dir.mkdir(parents=True, exist_ok=True)
        self._fsync_raw = fsync_raw
        self._export_dir = (
            Path(export_dir).resolve(strict=False) if export_dir is not None else None
        )
        if self._export_dir is not None:
            self._export_dir.mkdir(parents=True, exist_ok=True)
        self._retrieval_settings = retrieval_settings
        self._key_aliases = dict(key_aliases or {})
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

    def put_record(self, rec: MemoryRecord) -> str:
        existing = self.get_record(rec.id)
        if existing is not None:
            return rec.id
        values = self._record_insert_values(rec)
        with self._lock, self._connection() as connection, connection:
            try:
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
            except sqlite3.IntegrityError as error:
                if rec.status == "confirmed" and rec.key is not None:
                    raise JarvisMemoryError(
                        "같은 key에 confirmed 기억이 이미 존재합니다.",
                        {"key": rec.key, "record_id": rec.id},
                    ) from error
                raise JarvisMemoryError(
                    "기억 레코드를 저장하지 못했습니다.",
                    {"record_id": rec.id},
                ) from error
        return rec.id

    def get_record(self, record_id: str) -> MemoryRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM records WHERE id = ?", (record_id,)
            ).fetchone()
        return None if row is None else self._row_to_record(row)

    def confirm(self, record_id: str, at: datetime) -> MemoryRecord:
        _validate_time(at, "at")
        with self._lock, self._connection() as connection, connection:
            row = connection.execute(
                "SELECT * FROM records WHERE id = ?", (record_id,)
            ).fetchone()
            if row is None:
                raise JarvisMemoryError(
                    "확정할 기억 레코드를 찾을 수 없습니다.",
                    {"record_id": record_id},
                )
            current = self._row_to_record(row)
            assert_transition_allowed(current.status, "confirmed")
            try:
                connection.execute(
                    """
                    UPDATE records
                    SET status = 'confirmed', updated_at = ?
                    WHERE id = ?
                    """,
                    (at.isoformat(timespec="milliseconds"), record_id),
                )
            except sqlite3.IntegrityError as error:
                if current.key is not None:
                    raise JarvisMemoryError(
                        "같은 key에 confirmed 기억이 이미 존재합니다.",
                        {"key": current.key, "record_id": record_id},
                    ) from error
                raise JarvisMemoryError(
                    "기억 레코드를 확정하지 못했습니다.",
                    {"record_id": record_id},
                ) from error
        confirmed = self.get_record(record_id)
        if confirmed is None:
            raise MemoryCorrupted("확정한 기억 레코드를 다시 읽을 수 없습니다.")
        return confirmed

    def supersede(self, old_id: str, new_id: str, at: datetime) -> None:
        _validate_time(at, "at")
        with self._lock, self._connection() as connection, connection:
            old_row = connection.execute(
                "SELECT * FROM records WHERE id = ?", (old_id,)
            ).fetchone()
            new_row = connection.execute(
                "SELECT * FROM records WHERE id = ?", (new_id,)
            ).fetchone()
            if old_row is None:
                raise JarvisMemoryError(
                    "supersede 대상 기억 레코드를 찾을 수 없습니다.",
                    {"record_id": old_id},
                )
            if new_row is None:
                raise JarvisMemoryError(
                    "supersede 후보 기억 레코드를 찾을 수 없습니다.",
                    {"record_id": new_id},
                )
            old = self._row_to_record(old_row)
            assert_transition_allowed(old.status, "superseded")
            connection.execute(
                """
                UPDATE records
                SET status = 'superseded', updated_at = ?
                WHERE id = ?
                """,
                (at.isoformat(timespec="milliseconds"), old_id),
            )

    def soft_delete(self, record_id: str, reason: str, at: datetime) -> None:
        _validate_time(at, "at")
        if not reason.strip():
            raise ValueError("delete_reason은 비어 있을 수 없습니다")
        with self._lock, self._connection() as connection, connection:
            row = connection.execute(
                "SELECT * FROM records WHERE id = ?", (record_id,)
            ).fetchone()
            if row is None:
                raise JarvisMemoryError(
                    "삭제할 기억 레코드를 찾을 수 없습니다.",
                    {"record_id": record_id},
                )
            current = self._row_to_record(row)
            assert_transition_allowed(current.status, "deleted")
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

    def list_records(
        self,
        *,
        status: RecordStatus | None = None,
        kind: RecordKind | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        if limit < 0 or offset < 0:
            raise ValueError("limit과 offset은 0 이상이어야 합니다")
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT * FROM records
            {where}
            ORDER BY updated_at DESC, id DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def search(self, q: MemoryQuery) -> MemorySearchResult:
        now = q.now if q.now is not None else datetime.now().astimezone()
        _validate_time(now, "now")
        settings = self._retrieval_settings
        min_score = float(getattr(settings, "min_score", 0.15) if settings else 0.15)
        max_candidates = int(getattr(settings, "max_candidates", 3) if settings else 3)
        kind_weights = getattr(settings, "kind_weights", {}) if settings else {}
        half_life_days = getattr(settings, "half_life_days", {}) if settings else {}

        search_statuses: tuple[RecordStatus, ...] = tuple(
            status for status in q.statuses if status not in {"deleted", "superseded"}
        )
        if not search_statuses and not q.include_candidates:
            return MemorySearchResult((), ())

        confirmed_scored: list[ScoredRecord] = []
        candidate_scored: list[ScoredRecord] = []
        seen: set[str] = set()

        def add_scored(item: ScoredRecord) -> None:
            if item.record.id in seen:
                return
            seen.add(item.record.id)
            if item.record.status == "candidate":
                candidate_scored.append(item)
            else:
                confirmed_scored.append(item)

        key_candidates = extract_key_candidates(q.text, self._key_aliases)
        if key_candidates:
            placeholders = ", ".join("?" for _ in key_candidates)
            status_placeholders = ", ".join("?" for _ in search_statuses)
            kind_placeholders = ", ".join("?" for _ in q.kinds)
            params: list[Any] = [
                *key_candidates,
                *search_statuses,
                *q.kinds,
            ]
            query = f"""
                SELECT * FROM records
                WHERE key IN ({placeholders})
                  AND status IN ({status_placeholders})
                  AND kind IN ({kind_placeholders})
            """
            with self._connection() as connection:
                rows = connection.execute(query, params).fetchall()
            for row in rows:
                record = self._row_to_record(row)
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

        if q.include_candidates and "candidate" not in search_statuses:
            candidate_statuses: tuple[RecordStatus, ...] = ("candidate",)
        else:
            candidate_statuses = ()

        fts_query = fts_match_query(q.text)
        if fts_query:
            for statuses in (search_statuses, candidate_statuses):
                if not statuses:
                    continue
                status_placeholders = ", ".join("?" for _ in statuses)
                kind_placeholders = ", ".join("?" for _ in q.kinds)
                params = [fts_query, *statuses, *q.kinds]
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
                with self._connection() as connection:
                    try:
                        rows = connection.execute(sql, params).fetchall()
                    except sqlite3.OperationalError:
                        sql = f"""
                            SELECT r.*, 0.0 AS bm25_rank
                            FROM records_fts
                            JOIN records r ON r.rowid = records_fts.rowid
                            WHERE records_fts MATCH ?
                              AND r.status IN ({status_placeholders})
                              AND r.kind IN ({kind_placeholders})
                            LIMIT 40
                        """
                        rows = connection.execute(sql, params).fetchall()
                for row in rows:
                    record = self._row_to_record(row)
                    raw_rank = row["bm25_rank"]
                    try:
                        relevance = (
                            normalize_bm25(float(raw_rank))
                            if raw_rank is not None
                            else 1.0
                        )
                    except (TypeError, ValueError):
                        relevance = 1.0
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

        return finalize_search(
            confirmed_scored,
            candidate_scored,
            top_k=q.top_k,
            min_score=min_score,
            max_candidates=max_candidates if q.include_candidates else 0,
        )

    def export(self, dest: Path, *, include_raw: bool) -> Path:
        target = Path(dest)
        if target.is_dir() or not target.suffix:
            target.mkdir(parents=True, exist_ok=True)
            export_file = target / "records.jsonl"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            export_file = target

        records = self.list_records(limit=1_000_000, offset=0)
        lines = [
            json.dumps(
                self._record_to_export_dict(record),
                ensure_ascii=False,
                allow_nan=False,
            )
            for record in records
            if record.status != "deleted"
        ]
        payload = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        write_atomic(export_file, payload)

        if include_raw:
            raw_dest = export_file.parent / "raw"
            raw_dest.mkdir(parents=True, exist_ok=True)
            for raw_file in self._raw_dir.glob("*.jsonl"):
                shutil.copy2(raw_file, raw_dest / raw_file.name)
        return export_file

    def usage_bytes(self) -> int:
        total = 0
        if self._database_path.is_file():
            total += self._database_path.stat().st_size
        if self._raw_dir.is_dir():
            for path in self._raw_dir.rglob("*"):
                if path.is_file():
                    total += path.stat().st_size
        return total

    def integrity_check(self) -> list[str]:
        problems: list[str] = []
        try:
            with self._connection() as connection:
                integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
                if integrity != "ok":
                    problems.append(f"pragma integrity_check: {integrity}")
                try:
                    connection.execute(
                        "INSERT INTO records_fts(records_fts) VALUES('integrity-check')"
                    )
                except sqlite3.Error as error:
                    problems.append(f"records_fts integrity-check: {error}")
                try:
                    connection.execute(
                        "INSERT INTO doc_chunks_fts(doc_chunks_fts) VALUES('integrity-check')"
                    )
                except sqlite3.Error as error:
                    problems.append(f"doc_chunks_fts integrity-check: {error}")
        except JarvisMemoryError as error:
            problems.append(str(error.user_message))
        return problems

    def _record_insert_values(self, rec: MemoryRecord) -> tuple[Any, ...]:
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

    def _row_to_record(self, row: sqlite3.Row) -> MemoryRecord:
        try:
            tags_raw = json.loads(str(row["tags"]))
            if not isinstance(tags_raw, list):
                raise ValueError("tags must be a JSON array")
            tags = tuple(str(item) for item in tags_raw)
            source_session_id = row["source_session_id"]
            if source_session_id is None:
                raise MemoryCorrupted("기억 레코드 source_session_id가 없습니다.")
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
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise MemoryCorrupted("기억 레코드 행의 값이 손상되었습니다.") from error

    def _record_to_export_dict(self, record: MemoryRecord) -> dict[str, Any]:
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


SqliteMemoryStore = SQLiteSessionStore


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

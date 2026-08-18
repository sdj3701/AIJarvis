"""Append-only audit log writer with hash chain integrity."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.core.canonical import canonical_json
from app.core.clock import Clock

_ZERO_HASH = "0" * 64
_AUDIT_VERSION = 1

AuditIssueKind = Literal[
    "prev_hash_mismatch",
    "seq_not_monotonic",
    "seq_duplicate",
    "entry_hash_mismatch",
    "broken_json",
    "empty",
]


@dataclass(frozen=True, slots=True)
class AuditVerifyReport:
    """Structured result for gate --verify-audit and tests."""

    ok: bool
    files: int
    entries: int
    last_seq: int
    last_hash: str
    issue_kind: AuditIssueKind | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "files": self.files,
            "entries": self.entries,
            "last_seq": self.last_seq,
            "last_hash": self.last_hash,
            "issue_kind": self.issue_kind,
            "error": self.error,
        }


@dataclass
class JsonlAuditWriter:
    """Write tool audit records under data_root/logs with monotonic seq and hash chain."""

    logs_dir: Path
    database_path: Path
    clock: Clock
    fsync: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _prev_hash: str = _ZERO_HASH
    _db_ready: bool = False

    def __post_init__(self) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def write(self, record: Mapping[str, Any]) -> None:
        with self._lock:
            self._ensure_db()
            seq = _next_audit_seq(self.database_path)
            ts = self.clock.now().isoformat(timespec="milliseconds")
            body = dict(record)
            body.setdefault("v", _AUDIT_VERSION)
            body["seq"] = seq
            body["ts"] = ts
            body["prev_hash"] = self._prev_hash
            hash_body = {
                key: value for key, value in body.items() if key not in {"prev_hash", "entry_hash"}
            }
            entry_hash = _entry_hash(self._prev_hash, hash_body)
            body["entry_hash"] = entry_hash
            line = json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n"
            path = self._audit_path(ts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line)
                stream.flush()
                if self.fsync:
                    import os

                    os.fsync(stream.fileno())
            self._prev_hash = entry_hash
            _store_prev_hash(self.database_path, entry_hash)

    def _ensure_db(self) -> None:
        if self._db_ready:
            return
        try:
            self._prev_hash = _load_prev_hash(self.database_path)
        except sqlite3.OperationalError:
            self._prev_hash = _ZERO_HASH
        self._db_ready = True

    def _audit_path(self, ts_text: str) -> Path:
        day = ts_text[:10]
        return self.logs_dir / f"audit-{day}.jsonl"


def verify_audit_chain(logs_dir: Path) -> tuple[bool, str | None]:
    """Return (ok, error_message). Walk all audit files in date order."""
    report = verify_audit_chain_report(logs_dir)
    return report.ok, report.error


def verify_audit_chain_report(logs_dir: Path) -> AuditVerifyReport:
    """Verify hash chain without modifying logs. Distinguishes common failure modes."""
    files = sorted(logs_dir.glob("audit-*.jsonl"))
    if not files:
        return AuditVerifyReport(
            ok=True,
            files=0,
            entries=0,
            last_seq=0,
            last_hash=_ZERO_HASH,
            issue_kind="empty",
            error=None,
        )

    prev_hash = _ZERO_HASH
    last_seq = 0
    entries = 0
    seen_seq: set[int] = set()

    for path in files:
        raw = path.read_text(encoding="utf-8")
        lines = raw.splitlines()
        for line_no, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # Trailing partial line after crash is reported separately from mid-file corruption.
                is_last_line = line_no == len(lines) and not raw.endswith("\n")
                kind: AuditIssueKind = "broken_json"
                where = "trailing partial line" if is_last_line else "json"
                return AuditVerifyReport(
                    ok=False,
                    files=len(files),
                    entries=entries,
                    last_seq=last_seq,
                    last_hash=prev_hash,
                    issue_kind=kind,
                    error=f"{path.name}:{line_no} {where} parse failed",
                )

            expected_prev = record.get("prev_hash")
            if expected_prev != prev_hash:
                return AuditVerifyReport(
                    ok=False,
                    files=len(files),
                    entries=entries,
                    last_seq=last_seq,
                    last_hash=prev_hash,
                    issue_kind="prev_hash_mismatch",
                    error=f"{path.name}:{line_no} prev_hash mismatch",
                )

            seq = int(record["seq"])
            if seq in seen_seq:
                return AuditVerifyReport(
                    ok=False,
                    files=len(files),
                    entries=entries,
                    last_seq=last_seq,
                    last_hash=prev_hash,
                    issue_kind="seq_duplicate",
                    error=f"{path.name}:{line_no} duplicate seq {seq}",
                )
            if seq <= last_seq:
                return AuditVerifyReport(
                    ok=False,
                    files=len(files),
                    entries=entries,
                    last_seq=last_seq,
                    last_hash=prev_hash,
                    issue_kind="seq_not_monotonic",
                    error=f"{path.name}:{line_no} seq not monotonic ({seq} <= {last_seq})",
                )
            seen_seq.add(seq)
            last_seq = seq

            entry_hash = record.pop("entry_hash")
            stored_prev = record.pop("prev_hash")
            computed = _entry_hash(stored_prev, record)
            if computed != entry_hash:
                return AuditVerifyReport(
                    ok=False,
                    files=len(files),
                    entries=entries,
                    last_seq=last_seq,
                    last_hash=prev_hash,
                    issue_kind="entry_hash_mismatch",
                    error=f"{path.name}:{line_no} entry_hash mismatch",
                )
            prev_hash = entry_hash
            entries += 1

    return AuditVerifyReport(
        ok=True,
        files=len(files),
        entries=entries,
        last_seq=last_seq,
        last_hash=prev_hash,
    )


def read_audit_records(logs_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(logs_dir.glob("audit-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def _entry_hash(prev_hash: str, record_without_hashes: Mapping[str, Any]) -> str:
    payload = prev_hash.encode("utf-8") + canonical_json(dict(record_without_hashes))
    return hashlib.sha256(payload).hexdigest()


def _next_audit_seq(database_path: Path) -> int:
    with sqlite3.connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT value FROM meta WHERE key='audit_seq'"
        ).fetchone()
        if row is None:
            connection.execute("ROLLBACK")
            raise sqlite3.OperationalError("meta.audit_seq is not initialized")
        current = int(row[0]) if row is not None else 0
        new_value = current + 1
        connection.execute(
            "UPDATE meta SET value=? WHERE key='audit_seq'",
            (str(new_value),),
        )
        connection.commit()
        return new_value


def _load_prev_hash(database_path: Path) -> str:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT value FROM meta WHERE key='audit_prev_hash'"
        ).fetchone()
        if row is None:
            return _ZERO_HASH
        return str(row[0])


def _store_prev_hash(database_path: Path, value: str) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('audit_prev_hash', ?)",
            (value,),
        )
        connection.commit()

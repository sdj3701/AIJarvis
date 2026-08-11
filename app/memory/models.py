"""Phase 2 memory record contracts aligned with DESIGN 5.2 and SCHEMAS 6-7."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from app.core.ids import new_id

RecordKind = Literal["fact", "correction", "summary", "doc_chunk"]
RecordStatus = Literal["candidate", "confirmed", "superseded", "deleted"]
SourceKind = Literal["user_explicit", "summarizer", "import"]
Sensitivity = Literal["normal", "sensitive", "secret"]
MatchKind = Literal["fts", "embedding", "key_exact"]

KEY_PREFIXES = (
    "identity.",
    "pref.",
    "env.",
    "project.",
    "contact.",
    "fact.",
)

_ALLOWED_TRANSITIONS: dict[RecordStatus, frozenset[RecordStatus]] = {
    "candidate": frozenset({"confirmed", "deleted"}),
    "confirmed": frozenset({"superseded", "deleted"}),
    "superseded": frozenset(),
    "deleted": frozenset(),
}

_KEY_PATTERN = re.compile(
    r"^(identity|pref|env|project|contact|fact)\.[A-Za-z0-9_.-]+$"
)


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    id: str
    schema_version: int
    kind: RecordKind
    key: str | None
    value: str
    status: RecordStatus
    source_session_id: str
    source_turn_id: str | None
    source_kind: SourceKind
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    sensitivity: Sensitivity
    supersedes: str | None
    tags: tuple[str, ...]
    deleted_at: datetime | None = None
    delete_reason: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("memory schema_version must be 1")
        if self.kind not in {"fact", "correction", "summary", "doc_chunk"}:
            raise ValueError("invalid memory kind")
        if self.status not in {"candidate", "confirmed", "superseded", "deleted"}:
            raise ValueError("invalid memory status")
        if self.source_kind not in {"user_explicit", "summarizer", "import"}:
            raise ValueError("invalid source_kind")
        if self.sensitivity not in {"normal", "sensitive", "secret"}:
            raise ValueError("invalid sensitivity")
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("memory value must be a non-empty string")
        if self.kind in {"fact", "correction"} and not self.key:
            raise ValueError("fact/correction require a key")
        if self.key is not None and not validate_memory_key(self.key):
            raise ValueError("memory key namespace is invalid")
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")
        if self.expires_at is not None:
            _require_aware(self.expires_at, "expires_at")
        if self.deleted_at is not None:
            _require_aware(self.deleted_at, "deleted_at")


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    text: str
    kinds: tuple[RecordKind, ...] = ("correction", "fact", "summary")
    statuses: tuple[RecordStatus, ...] = ("confirmed",)
    top_k: int = 8
    include_candidates: bool = False
    now: datetime | None = None


@dataclass(frozen=True, slots=True)
class ScoredRecord:
    record: MemoryRecord
    score: float
    matched_on: MatchKind


@dataclass(frozen=True, slots=True)
class MemorySearchResult:
    matches: tuple[ScoredRecord, ...]
    candidates: tuple[ScoredRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class FactCandidate:
    id: str
    key: str
    value: str
    status: Literal["candidate"]
    confidence: float
    evidence_turn_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.evidence_turn_ids:
            raise ValueError("evidence_turn_ids is required")
        if not validate_memory_key(self.key):
            raise ValueError("fact candidate key is invalid")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class SessionSummary:
    schema_version: int
    session_id: str
    summary_record_id: str
    summary: str
    turn_count: int
    fact_candidates: tuple[FactCandidate, ...]
    corrections: tuple[FactCandidate, ...]
    tags: tuple[str, ...]
    raw_path: str
    generated_by: dict[str, object]
    cost_usd: Decimal


def validate_memory_key(key: str) -> bool:
    return isinstance(key, str) and _KEY_PATTERN.fullmatch(key) is not None


def assert_transition_allowed(current: RecordStatus, target: RecordStatus) -> None:
    if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        from app.core.errors import MemoryError as JarvisMemoryError

        raise JarvisMemoryError(
            "허용되지 않는 기억 상태 전이입니다.",
            {"from": current, "to": target},
        )


def new_fact_id() -> str:
    return new_id("fact")


def new_summary_id() -> str:
    return new_id("sum")


def _require_aware(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")

"""SQLite-backed local data-store foundations."""

from app.memory.migrations import SCHEMA_VERSION, initialize_database
from app.memory.models import (
    MemoryQuery,
    MemoryRecord,
    MemorySearchResult,
    ScoredRecord,
    assert_transition_allowed,
    new_fact_id,
    new_summary_id,
    validate_memory_key,
)
from app.memory.store import (
    RawReadResult,
    RawRecord,
    SessionRow,
    SqliteMemoryStore,
    SQLiteSessionStore,
)

__all__ = [
    "SCHEMA_VERSION",
    "MemoryQuery",
    "MemoryRecord",
    "MemorySearchResult",
    "RawReadResult",
    "RawRecord",
    "SQLiteSessionStore",
    "ScoredRecord",
    "SessionRow",
    "SqliteMemoryStore",
    "assert_transition_allowed",
    "initialize_database",
    "new_fact_id",
    "new_summary_id",
    "validate_memory_key",
]

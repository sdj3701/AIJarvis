"""SQLite-backed local data-store foundations."""

from app.memory.migrations import SCHEMA_VERSION, initialize_database

__all__ = ["SCHEMA_VERSION", "initialize_database"]

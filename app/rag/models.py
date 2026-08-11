"""Structured RAG search and indexing models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    published_at: datetime | None
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    requested_url: str
    final_url: str
    title: str
    content: str
    content_type: str
    fetched_at: datetime
    truncated: bool


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    relative_path: str
    ordinal: int
    text: str
    start_char: int
    end_char: int
    transfer_class: Literal["local_only", "api_allowed"]
    score: float


@dataclass(frozen=True, slots=True)
class IndexReport:
    indexed: int
    updated: int
    removed: int
    skipped: int
    errors: tuple[str, ...]

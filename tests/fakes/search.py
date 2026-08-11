"""Deterministic search provider for offline tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.rag.models import SearchHit
from app.rag.search_provider import SearchFailed


@dataclass
class FakeSearchProvider:
    hits: list[SearchHit] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    fail_with: SearchFailed | None = None

    def search(
        self,
        query: str,
        *,
        max_results: int,
        timeout_s: float,
    ) -> tuple[SearchHit, ...]:
        del timeout_s
        self.calls.append(query)
        if self.fail_with is not None:
            raise self.fail_with
        return tuple(self.hits[:max_results])

    def add_hit(
        self,
        *,
        title: str,
        url: str,
        snippet: str,
        fetched_at: datetime | None = None,
    ) -> None:
        self.hits.append(
            SearchHit(
                title=title,
                url=url,
                snippet=snippet,
                published_at=None,
                fetched_at=fetched_at or datetime.now().astimezone(),
            )
        )

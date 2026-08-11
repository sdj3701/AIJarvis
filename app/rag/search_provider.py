"""Web search provider protocol and DuckDuckGo implementation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.errors import JarvisError
from app.rag.models import SearchHit


class SearchFailed(JarvisError):
    """Search provider returned an error or unusable response."""


class SearchProvider(Protocol):
    def search(
        self,
        query: str,
        *,
        max_results: int,
        timeout_s: float,
    ) -> tuple[SearchHit, ...]: ...


@dataclass(frozen=True, slots=True)
class DuckDuckGoProvider:
    def search(
        self,
        query: str,
        *,
        max_results: int,
        timeout_s: float,
    ) -> tuple[SearchHit, ...]:
        try:
            from ddgs import DDGS
        except ImportError as error:
            raise SearchFailed(
                "검색 패키지가 설치되지 않았습니다. "
                "pip install jarvis-assistant[search]를 실행하세요.",
                {"provider": "duckduckgo"},
            ) from error

        fetched_at = datetime.now().astimezone()
        try:
            raw_results: object = DDGS(timeout=max(1, math.ceil(timeout_s))).text(
                query,
                max_results=max_results,
            )
        except Exception as error:
            raise SearchFailed(
                "웹 검색 요청에 실패했습니다.",
                {"provider": "duckduckgo", "error_type": type(error).__name__},
            ) from error

        if not isinstance(raw_results, list):
            raise SearchFailed("웹 검색 응답 형식이 올바르지 않습니다.")

        hits: list[SearchHit] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            hits.append(
                SearchHit(
                    title=str(item.get("title") or ""),
                    url=str(item.get("href") or item.get("url") or ""),
                    snippet=str(item.get("body") or item.get("snippet") or ""),
                    published_at=None,
                    fetched_at=fetched_at,
                )
            )
        return tuple(hits)


def build_search_provider(provider_name: str) -> SearchProvider:
    if provider_name == "duckduckgo":
        return DuckDuckGoProvider()
    raise SearchFailed(f"지원하지 않는 검색 제공자입니다: {provider_name}")

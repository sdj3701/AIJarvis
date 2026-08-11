"""Phase 3 read-only search tool implementations."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.budget import BudgetGuard
from app.privacy.gate import PrivacyGate
from app.rag.fetcher import UrlFetcher
from app.rag.indexer import DocumentIndexer
from app.rag.models import RetrievedChunk, SearchHit
from app.rag.search_provider import SearchProvider
from app.tools.base import ToolContext, ToolResult, ToolSpec
from app.tools.registry import validate_tool_args


def _duration_ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))


@dataclass
class WebSearchTool:
    spec: ToolSpec
    provider: SearchProvider
    gate: PrivacyGate
    budget: BudgetGuard
    default_max_results: int
    cost_per_request: Decimal

    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        validated = validate_tool_args(self.spec.json_schema, args)
        query = str(validated["query"])
        max_results = int(validated.get("max_results", self.default_max_results))
        external = self.gate.for_external_text(query, purpose="search_query")
        if external.text is None:
            return ToolResult(
                ok=False,
                output="검색어가 프라이버시 정책으로 차단되었습니다.",
                data=None,
                error=external.reason,
                changed_paths=(),
                duration_ms=_duration_ms(start),
                truncated=False,
                untrusted=True,
            )
        self.budget.check("search", self.cost_per_request, ctx=tctx.ctx)
        try:
            hits = self.provider.search(
                external.text,
                max_results=max_results,
                timeout_s=self.spec.timeout_s,
            )
        except Exception as error:
            message = getattr(error, "user_message", "웹 검색에 실패했습니다.")
            return ToolResult(
                ok=False,
                output=message,
                data={"query": query, "hits": []},
                error=message,
                changed_paths=(),
                duration_ms=_duration_ms(start),
                truncated=False,
                untrusted=True,
            )
        self.budget.record_charge("search", self.cost_per_request, ctx=tctx.ctx)
        data = {"query": query, "hits": [_hit_dict(hit) for hit in hits]}
        output = "\n".join(f"- {hit.title} ({hit.url})" for hit in hits) or "검색 결과가 없습니다."
        return ToolResult(
            ok=True,
            output=output,
            data=data,
            error=None,
            changed_paths=(),
            duration_ms=_duration_ms(start),
            truncated=False,
            untrusted=True,
        )


@dataclass
class DocSearchTool:
    spec: ToolSpec
    indexer: DocumentIndexer
    default_max_results: int

    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        del tctx
        start = time.monotonic()
        validated = validate_tool_args(self.spec.json_schema, args)
        query = str(validated["query"])
        max_results = int(validated.get("max_results", self.default_max_results))
        hits = self.indexer.search(query, max_results=max_results)
        data = {"query": query, "hits": [_doc_hit_dict(hit) for hit in hits]}
        if not hits:
            output = "로컬 문서에서 관련 결과를 찾지 못했습니다."
        else:
            output = "\n".join(
                f"- {hit.relative_path}#{hit.ordinal}: {hit.text[:120]}" for hit in hits
            )
        return ToolResult(
            ok=True,
            output=output,
            data=data,
            error=None,
            changed_paths=(),
            duration_ms=_duration_ms(start),
            truncated=False,
            untrusted=True,
        )


@dataclass
class FetchUrlTool:
    spec: ToolSpec
    fetcher: UrlFetcher

    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        del tctx
        start = time.monotonic()
        validated = validate_tool_args(self.spec.json_schema, args)
        url = str(validated["url"])
        try:
            self.fetcher.validate_url(url)
            document = self.fetcher.fetch(url, timeout_s=self.spec.timeout_s)
        except Exception as error:
            message = getattr(error, "user_message", "URL을 가져올 수 없습니다.")
            return ToolResult(
                ok=False,
                output=message,
                data=None,
                error=message,
                changed_paths=(),
                duration_ms=_duration_ms(start),
                truncated=False,
                untrusted=True,
            )
        data = {
            "requested_url": document.requested_url,
            "final_url": document.final_url,
            "title": document.title,
            "content": document.content,
            "content_type": document.content_type,
            "fetched_at": document.fetched_at.isoformat(timespec="seconds"),
            "truncated": document.truncated,
        }
        return ToolResult(
            ok=True,
            output=document.content[:500],
            data=data,
            error=None,
            changed_paths=(),
            duration_ms=_duration_ms(start),
            truncated=document.truncated,
            untrusted=True,
        )


def _hit_dict(hit: SearchHit) -> dict[str, Any]:
    return {
        "title": hit.title,
        "url": hit.url,
        "snippet": hit.snippet,
        "published_at": (
            hit.published_at.isoformat(timespec="seconds")
            if hit.published_at
            else None
        ),
        "fetched_at": hit.fetched_at.isoformat(timespec="seconds"),
    }


def _doc_hit_dict(hit: RetrievedChunk) -> dict[str, Any]:
    return {
        "chunk_id": hit.chunk_id,
        "doc_id": hit.doc_id,
        "relative_path": hit.relative_path,
        "ordinal": hit.ordinal,
        "text": hit.text,
        "start_char": hit.start_char,
        "end_char": hit.end_char,
        "transfer_class": hit.transfer_class,
        "score": hit.score,
    }

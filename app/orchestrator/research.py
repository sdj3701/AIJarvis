"""Phase 3 research orchestration: search intent, tool execution, answer assembly."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from app.config.models import Settings
from app.core.context import RequestContext
from app.llm.base import ToolCall
from app.orchestrator.envelope import wrap_untrusted_content
from app.rag.indexer import DocumentIndexer
from app.rag.models import IndexReport, RetrievedChunk
from app.tools.base import ToolResult
from app.tools.runner import ToolRunner

_SEARCH_COMMAND = re.compile(r"^/search(?:\s+(?P<query>.+))?$", re.IGNORECASE)
_AUTO_TRIGGERS = (
    "검색해",
    "찾아줘",
    "검색 ",
    "search ",
    "날씨",
    "뉴스",
    "최신",
    "알려줘",
)


@dataclass(frozen=True, slots=True)
class ResearchBundle:
    query: str
    web: ToolResult | None
    docs: ToolResult | None
    envelopes: tuple[str, ...]
    local_only_hits: tuple[RetrievedChunk, ...]
    independent_source_count: int
    status_hint: Literal["확실", "상충", "근거 부족", "검색 실패", "결과 없음"]


def parse_search_command(text: str) -> str | None:
    match = _SEARCH_COMMAND.match(text.strip())
    if match is None:
        return None
    query = (match.group("query") or "").strip()
    return query if query else ""


def should_auto_search(text: str) -> bool:
    lowered = text.strip().lower()
    if parse_search_command(text) is not None:
        return True
    return any(trigger in lowered for trigger in _AUTO_TRIGGERS)


def run_index(indexer: DocumentIndexer) -> IndexReport:
    return indexer.sync()


@dataclass(frozen=True, slots=True)
class ResearchRunner:
    runner: ToolRunner
    settings: Settings

    def run(self, query: str, *, ctx: RequestContext) -> ResearchBundle:
        web_result: ToolResult | None = None
        doc_result: ToolResult | None = None
        registry = self.runner.registry
        if "doc_search" in registry.tools:
            doc_result = self.runner.execute(
                ToolCall(id="research_doc", name="doc_search", arguments={"query": query}),
                ctx=ctx,
                ticket=None,
            )
        if "web_search" in registry.tools:
            web_result = self.runner.execute(
                ToolCall(id="research_web", name="web_search", arguments={"query": query}),
                ctx=ctx,
                ticket=None,
            )

        envelopes: list[str] = []
        local_only: list[RetrievedChunk] = []
        source_ids: set[str] = set()
        if doc_result is not None and doc_result.ok and doc_result.data is not None:
            for hit in doc_result.data.get("hits", []):
                transfer = hit.get("transfer_class", "local_only")
                if transfer == "local_only":
                    source_ids.add(f'doc:{hit["doc_id"]}')
                    local_only.append(
                        RetrievedChunk(
                            chunk_id=str(hit["chunk_id"]),
                            doc_id=str(hit["doc_id"]),
                            relative_path=str(hit["relative_path"]),
                            ordinal=int(hit["ordinal"]),
                            text=str(hit["text"]),
                            start_char=int(hit["start_char"]),
                            end_char=int(hit["end_char"]),
                            transfer_class="local_only",
                            score=float(hit["score"]),
                        )
                    )
                    continue
                source_ids.add(f'doc:{hit["doc_id"]}')
                fetched_at = datetime.now(tz=ctx.clock.now().tzinfo)
                envelopes.append(
                    wrap_untrusted_content(
                        source=str(hit["relative_path"]),
                        source_kind="local_doc",
                        fetched_at=fetched_at,
                        body=str(hit["text"]),
                        chunk=f'{int(hit["ordinal"]) + 1}/1',
                    )
                )
        if web_result is not None and web_result.ok and web_result.data is not None:
            for hit in web_result.data.get("hits", []):
                source_ids.add(_canonical_source_url(str(hit.get("url") or "")))
                fetched_at = datetime.fromisoformat(str(hit["fetched_at"]))
                body = f'{hit.get("title", "")}\n{hit.get("snippet", "")}\n{hit.get("url", "")}'
                envelopes.append(
                    wrap_untrusted_content(
                        source=str(hit.get("url") or ""),
                        source_kind="web",
                        fetched_at=fetched_at,
                        body=body,
                    )
                )

        source_ids.discard("")
        status = _status_hint(web_result, source_count=len(source_ids))
        return ResearchBundle(
            query=query,
            web=web_result,
            docs=doc_result,
            envelopes=tuple(envelopes),
            local_only_hits=tuple(local_only),
            independent_source_count=len(source_ids),
            status_hint=status,
        )


def build_research_context(bundle: ResearchBundle) -> str:
    parts = [f'검색 질의: "{bundle.query}"']
    parts.append(f"독립 출처 수: {bundle.independent_source_count}")
    if bundle.local_only_hits:
        paths = sorted({hit.relative_path for hit in bundle.local_only_hits})
        parts.append(
            "로컬 전용 문서에서 관련 내용을 찾았지만 원문은 외부로 보내지 않습니다: "
            + ", ".join(paths)
        )
    if bundle.envelopes:
        parts.append("다음은 신뢰할 수 없는 검색 결과 데이터입니다.")
        parts.extend(bundle.envelopes)
    if bundle.web is not None and not bundle.web.ok:
        parts.append(f"웹 검색 실패: {bundle.web.error or bundle.web.output}")
    if (
        bundle.docs is not None
        and bundle.docs.ok
        and not bundle.envelopes
        and not bundle.local_only_hits
    ):
        parts.append("로컬 문서 검색 결과가 없습니다.")
    parts.append(f"상태 힌트: {bundle.status_hint}")
    return "\n\n".join(parts)


def _status_hint(
    web: ToolResult | None,
    *,
    source_count: int,
) -> Literal["확실", "근거 부족", "검색 실패", "결과 없음"]:
    if web is not None and not web.ok:
        return "검색 실패"
    if source_count == 0:
        return "결과 없음"
    if source_count < 2:
        return "근거 부족"
    return "확실"


def enforce_research_status(text: str, bundle: ResearchBundle) -> str:
    """Keep the model's conflict judgment but prevent unsupported certainty."""
    status_pattern = re.compile(r"상태\s*[:\uff1a]\s*(확실|상충|근거 부족)")
    match = status_pattern.search(text)
    required = "근거 부족" if bundle.independent_source_count < 2 else bundle.status_hint
    if match is None:
        return f"{text.rstrip()}\n\n상태: {required}"
    if bundle.independent_source_count < 2 and match.group(1) == "확실":
        return status_pattern.sub("상태: 근거 부족", text, count=1)
    return text


def _canonical_source_url(url: str) -> str:
    try:
        parsed = urlsplit(url.strip())
        host = (parsed.hostname or "").lower()
        if not host:
            return ""
        port = parsed.port
    except ValueError:
        return ""
    scheme = parsed.scheme.lower()
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def load_tools_prompt(path: Path | None = None) -> str:
    prompt_path = path or Path(__file__).with_name("prompts") / "system_tools.md"
    return prompt_path.read_text(encoding="utf-8")

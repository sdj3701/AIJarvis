# 파이썬 공부 | scripts/app/tools/impl/web_search.py
# 웹 검색을 도구 인터페이스로 제공합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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


# _duration_ms(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: start.
# 반환 타입 힌트: 정수(int).
def _duration_ms(start: float) -> int:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return max(0, int((time.monotonic() - start) * 1000))


# WebSearchTool: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class WebSearchTool:
    # spec: ToolSpec 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    spec: ToolSpec
    # provider: SearchProvider 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    provider: SearchProvider
    # gate: PrivacyGate 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    gate: PrivacyGate
    # budget: BudgetGuard 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    budget: BudgetGuard
    # default_max_results: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    default_max_results: int
    # cost_per_request: Decimal 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    cost_per_request: Decimal

    # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: args, tctx.
    # 반환 타입 힌트: ToolResult.
    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        # time.monotonic()의 반환값을 start에 대입합니다.
        start = time.monotonic()
        # validate_tool_args()의 반환값을 validated에 대입합니다.
        validated = validate_tool_args(self.spec.json_schema, args)
        # str()의 반환값을 query에 대입합니다.
        query = str(validated["query"])
        # int()의 반환값을 max_results에 대입합니다.
        max_results = int(validated.get("max_results", self.default_max_results))
        # self.gate.for_external_text()의 반환값을 external에 대입합니다.
        external = self.gate.for_external_text(query, purpose="search_query")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: external.text is None.
        if external.text is None:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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
        # self.budget.check()을 호출해 작업을 수행합니다.
        self.budget.check("search", self.cost_per_request, ctx=tctx.ctx)
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # self.provider.search()의 반환값을 hits에 대입합니다.
            hits = self.provider.search(
                external.text,
                max_results=max_results,
                timeout_s=self.spec.timeout_s,
            )
        # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except Exception as error:
            # getattr()의 반환값을 message에 대입합니다.
            message = getattr(error, "user_message", "웹 검색에 실패했습니다.")
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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
        # self.budget.record_charge()을 호출해 작업을 수행합니다.
        self.budget.record_charge("search", self.cost_per_request, ctx=tctx.ctx)
        # data에 딕셔너리(키와 값의 쌍)을 대입합니다.
        data = {"query": query, "hits": [_hit_dict(hit) for hit in hits]}
        # 오른쪽 식을 계산한 값을 output에 대입합니다.
        output = "\n".join(f"- {hit.title} ({hit.url})" for hit in hits) or "검색 결과가 없습니다."
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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


# DocSearchTool: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class DocSearchTool:
    # spec: ToolSpec 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    spec: ToolSpec
    # indexer: DocumentIndexer 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    indexer: DocumentIndexer
    # default_max_results: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    default_max_results: int

    # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: args, tctx.
    # 반환 타입 힌트: ToolResult.
    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del tctx
        # time.monotonic()의 반환값을 start에 대입합니다.
        start = time.monotonic()
        # validate_tool_args()의 반환값을 validated에 대입합니다.
        validated = validate_tool_args(self.spec.json_schema, args)
        # str()의 반환값을 query에 대입합니다.
        query = str(validated["query"])
        # int()의 반환값을 max_results에 대입합니다.
        max_results = int(validated.get("max_results", self.default_max_results))
        # self.indexer.search()의 반환값을 hits에 대입합니다.
        hits = self.indexer.search(query, max_results=max_results)
        from app.rag.document_context import document_context

        hits, structures = document_context(self.indexer, query, hits)
        # data에 딕셔너리(키와 값의 쌍)을 대입합니다.
        data = {
            "query": query,
            "hits": [_doc_hit_dict(hit) for hit in hits],
            "document_structures": list(structures),
            "diagnostics": dict(self.indexer.last_diagnostics),
        }
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not hits.
        if not hits:
            # output에 문자열을 대입합니다.
            output = "로컬 문서에서 관련 결과를 찾지 못했습니다."
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # '\n'.join()의 반환값을 output에 대입합니다.
            output = "\n".join(
                f"- {hit.relative_path}#{hit.ordinal}: {hit.text[:120]}" for hit in hits
            )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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


# FetchUrlTool: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class FetchUrlTool:
    # spec: ToolSpec 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    spec: ToolSpec
    # fetcher: UrlFetcher 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    fetcher: UrlFetcher

    # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: args, tctx.
    # 반환 타입 힌트: ToolResult.
    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del tctx
        # time.monotonic()의 반환값을 start에 대입합니다.
        start = time.monotonic()
        # validate_tool_args()의 반환값을 validated에 대입합니다.
        validated = validate_tool_args(self.spec.json_schema, args)
        # str()의 반환값을 url에 대입합니다.
        url = str(validated["url"])
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # self.fetcher.validate_url()으로 입력 형식과 허용 조건을 검사합니다.
            self.fetcher.validate_url(url)
            # self.fetcher.fetch()의 반환값을 document에 대입합니다.
            document = self.fetcher.fetch(url, timeout_s=self.spec.timeout_s)
        # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except Exception as error:
            # getattr()의 반환값을 message에 대입합니다.
            message = getattr(error, "user_message", "URL을 가져올 수 없습니다.")
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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
        # data에 딕셔너리(키와 값의 쌍)을 대입합니다.
        data = {
            "requested_url": document.requested_url,
            "final_url": document.final_url,
            "title": document.title,
            "content": document.content,
            "content_type": document.content_type,
            "fetched_at": document.fetched_at.isoformat(timespec="seconds"),
            "truncated": document.truncated,
        }
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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


# _hit_dict(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: hit.
# 반환 타입 힌트: dict[str, Any].
def _hit_dict(hit: SearchHit) -> dict[str, Any]:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return {
        "title": hit.title,
        "url": hit.url,
        "snippet": hit.snippet,
        "published_at": (
            hit.published_at.isoformat(timespec="seconds") if hit.published_at else None
        ),
        "fetched_at": hit.fetched_at.isoformat(timespec="seconds"),
    }


# _doc_hit_dict(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: hit.
# 반환 타입 힌트: dict[str, Any].
def _doc_hit_dict(hit: RetrievedChunk) -> dict[str, Any]:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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
        "rerank_score": hit.rerank_score,
        "title": hit.title,
        "pages": list(hit.pages),
        "structure": list(hit.structure),
        "spans": list(hit.spans),
    }

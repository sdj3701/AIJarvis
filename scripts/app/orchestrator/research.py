# 파이썬 공부 | scripts/app/orchestrator/research.py
# 검색이 필요한 요청을 판단하고 검색 결과를 답변으로 구성합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Phase 3 research orchestration: search intent, tool execution, answer assembly."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from app.config.models import Settings
from app.core.context import RequestContext
from app.llm.base import ToolCall
from app.orchestrator.envelope import wrap_untrusted_content
from app.orchestrator.query_plan import QueryPlan, plan_query
from app.rag.document_context import broad_question
from app.rag.document_parser import SourceSpan
from app.rag.grounding import GENERATION_INSTRUCTION, Evidence
from app.rag.indexer import DocumentIndexer
from app.rag.models import IndexReport, RetrievedChunk
from app.rag.passages import Passage, make_passages, question_parts
from app.tools.base import ToolResult
from app.tools.runner import ToolRunner

# re.compile()의 반환값을 _SEARCH_COMMAND에 대입합니다.
_SEARCH_COMMAND = re.compile(r"^/search(?:\s+(?P<query>.+))?$", re.IGNORECASE)
# _AUTO_TRIGGERS에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
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


_LOCAL_QUERY = re.compile(
    r"우리\s*회사|사내|내부\s*(?:문서|자료|규정)|로컬|연차|휴가|취업규칙|인사\s*규정"
)
_WEB_QUERY = re.compile(r"웹|인터넷|뉴스|날씨|최신|https?://", re.IGNORECASE)


def needs_web_search(query: str) -> bool:
    """Internal questions stay local; external searches require explicit intent."""
    return plan_query(query).route == "web"


# ResearchBundle: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class ResearchBundle:
    # query: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    query: str
    # web: ToolResult | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    web: ToolResult | None
    # docs: ToolResult | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    docs: ToolResult | None
    # envelopes: tuple[str, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    envelopes: tuple[str, ...]
    # local_only_hits: tuple[RetrievedChunk, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    local_only_hits: tuple[RetrievedChunk, ...]
    # independent_source_count: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    independent_source_count: int
    # status_hint: Literal['확실', '상충', '근거 부족', '검색 실패', '결과 없음'] 타입을 기대하는
    # 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    status_hint: Literal["근거 부족", "검색 실패", "결과 없음"]
    evidence: tuple[Evidence, ...] = ()
    questions: tuple[str, ...] = ()


# parse_search_command(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text.
# 반환 타입 힌트: str | None.
def parse_search_command(text: str) -> str | None:
    # _SEARCH_COMMAND.match()의 반환값을 match에 대입합니다.
    match = _SEARCH_COMMAND.match(text.strip())
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match is None.
    if match is None:
        # None을 반환하고 이 함수의 실행을 끝냅니다.
        return None
    # (match.group('query') or '').strip()의 반환값을 query에 대입합니다.
    query = (match.group("query") or "").strip()
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    return query if query else ""


# should_auto_search(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text.
# 반환 타입 힌트: 참/거짓(bool).
def should_auto_search(text: str) -> bool:
    # text.strip().lower()의 반환값을 lowered에 대입합니다.
    lowered = text.strip().lower()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: parse_search_command(text) is not None.
    if parse_search_command(text) is not None:
        # True을 반환하고 이 함수의 실행을 끝냅니다.
        return True
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return plan_query(lowered).route in {"local_doc", "web", "clarify"}


# run_index(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: indexer.
# 반환 타입 힌트: IndexReport.
def run_index(indexer: DocumentIndexer) -> IndexReport:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return indexer.sync()


# ResearchRunner: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class ResearchRunner:
    # runner: ToolRunner 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    runner: ToolRunner
    # settings: Settings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    settings: Settings

    # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: query, ctx.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: ResearchBundle.
    def run(
        self, query: str, *, ctx: RequestContext, plan: QueryPlan | None = None
    ) -> ResearchBundle:
        # web_result을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        web_result: ToolResult | None = None
        # doc_result을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        doc_result: ToolResult | None = None
        # 오른쪽 식을 계산한 값을 registry에 대입합니다.
        registry = self.runner.registry
        questions = question_parts(query)
        context_limit = (
            self.settings.rag.max_structured_chunks
            if broad_question(query)
            else self.settings.rag.max_chunks_per_answer
        )
        structures = {}
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'doc_search' in registry.tools.
        if "doc_search" in registry.tools:
            # self.runner.execute()의 반환값을 doc_result에 대입합니다.
            results = [
                self.runner.execute(
                    ToolCall(id=f"research_doc_{i}", name="doc_search", arguments={"query": part}),
                    ctx=ctx,
                    ticket=None,
                )
                for i, part in enumerate(questions, 1)
            ]
            doc_result = results[0]
            merged = {}
            # Round-robin avoids dropping the second question's best evidence first.
            for qid, result in enumerate(results, 1):
                for structure in (result.data or {}).get("document_structures", []):
                    key = structure["doc_id"]
                    if key not in structures:
                        structures[key] = {**structure, "question_ids": []}
                    structures[key]["question_ids"].append(qid)
            for rank in range(context_limit):
                for qid, result in enumerate(results, 1):
                    hits = (result.data or {}).get("hits", [])
                    if rank < len(hits):
                        hit = dict(hits[rank])
                        key = hit["chunk_id"]
                        if key not in merged:
                            merged[key] = {**hit, "question_ids": []}
                        merged[key]["question_ids"].append(qid)
            diagnostics = dict((doc_result.data or {}).get("diagnostics", {}))
            if any((r.data or {}).get("diagnostics", {}).get("source_stale") for r in results):
                diagnostics["source_stale"] = True
            if any(not r.ok for r in results):
                doc_result = next(r for r in results if not r.ok)
            else:
                doc_result = replace(
                    doc_result,
                    data={
                        "hits": list(merged.values())[:context_limit],
                        "document_structures": list(structures.values()),
                        "diagnostics": diagnostics,
                    },
                )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'web_search' in registry.tools.
        if "web_search" in registry.tools and (
            plan.route == "web" if plan is not None else needs_web_search(query)
        ):
            # self.runner.execute()의 반환값을 web_result에 대입합니다.
            web_result = self.runner.execute(
                ToolCall(id="research_web", name="web_search", arguments={"query": query}),
                ctx=ctx,
                ticket=None,
            )

        # envelopes에 리스트(순서가 있고 수정 가능)을 대입합니다.
        envelopes: list[str] = []
        evidence: list[Evidence] = []
        # local_only에 리스트(순서가 있고 수정 가능)을 대입합니다.
        local_only: list[RetrievedChunk] = []
        # set()의 반환값을 source_ids에 대입합니다.
        source_ids: set[str] = set()
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if doc_result is not None and doc_result.ok and doc_result.data is not None:
            # for 반복문: 대상의 항목을 하나씩 hit에 대입하며 아래 블록을 실행합니다.
            for hit in doc_result.data.get("hits", []):
                # hit.get()의 반환값을 transfer에 대입합니다.
                transfer = hit.get("transfer_class", "local_only")
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: transfer == 'local_only'.
                if transfer == "local_only":
                    # add 메서드를 호출해 항목이나 기록을 추가합니다.
                    source_ids.add(f"doc:{hit['doc_id']}")
                    # 리스트 끝에 항목 하나를 추가합니다.
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
                            title=str(hit.get("title", "")),
                            pages=tuple(hit.get("pages", [])),
                            structure=tuple(hit.get("structure", [])),
                            spans=tuple(hit.get("spans", [])),
                        )
                    )
                    # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                    if str(self.settings.llm.provider) != "ollama":
                        continue
                # add 메서드를 호출해 항목이나 기록을 추가합니다.
                source_ids.add(f"doc:{hit['doc_id']}")
                # datetime.now()의 반환값을 fetched_at에 대입합니다.
                fetched_at = datetime.now(tz=ctx.clock.now().tzinfo)
                body = self.runner.privacy.for_summarizer_text(str(hit["text"]))
                source_id = f"S{len(evidence) + 1}"
                source = f"{hit['relative_path']}#chunk={hit['chunk_id']}"
                context = ""
                if pages := hit.get("pages"):
                    source += "&page=" + ",".join(str(int(p)) for p in pages)
                    context = self.runner.privacy.for_summarizer_text(
                        "문서 위치(인용 본문 아님): "
                        + str(hit.get("title", ""))
                        + "\n"
                        + "\n".join(str(s) for s in hit.get("structure", []))
                    )
                passages = tuple(
                    replace(
                        p,
                        text=self.runner.privacy.for_summarizer_text(p.text),
                        location=self.runner.privacy.for_summarizer_text(p.location),
                        list_size=next(
                            (
                                v["size"]
                                for v in structures.get(hit["doc_id"], {}).get("lists", [])
                                if tuple(v["scope"]) == p.scope
                            ),
                            None,
                        ),
                    )
                    for p in make_passages(
                        str(hit["text"]),
                        source_id,
                        tuple(SourceSpan(**s) for s in hit.get("spans", [])),
                        include_headings=True,
                    )
                )
                evidence.append(
                    Evidence(
                        source_id,
                        source,
                        body,
                        context,
                        passages,
                        tuple(hit.get("question_ids", [])),
                    )
                )
                # 리스트 끝에 항목 하나를 추가합니다.
                envelopes.append(
                    wrap_untrusted_content(
                        source=source,
                        source_id=source_id,
                        source_kind="local_doc",
                        fetched_at=fetched_at,
                        body=(context + "\n\n" if context else "") + body,
                        chunk=str(int(hit["ordinal"]) + 1),
                    )
                )
        # A document outline is separate from retrieved body chunks. Its heading
        # text and PDF pages are copied from the full parsed source; counts are
        # application-computed and never inferred from the top-k result.
        for structure in structures.values():
            if (
                structure["transfer_class"] == "local_only"
                and str(self.settings.llm.provider) != "ollama"
            ):
                continue
            if not structure.get("outline") and not structure.get("removed"):
                continue
            sid = f"S{len(evidence) + 1}"
            structure_passages: list[Passage] = []
            for i, item in enumerate(structure.get("outline", [])):
                loc = " ".join(v for v in (item["chapter"], item["article"]) if v)
                loc += " · PDF " + ", ".join(map(str, item["pages"])) + "쪽"
                structure_passages.append(
                    Passage(
                        f"{sid}.H{i}",
                        item["text"],
                        loc,
                        (item["chapter"], item["article"], ""),
                        kind="heading",
                    )
                )
            for i, item in enumerate(structure.get("removed", [])):
                structure_passages.append(
                    Passage(
                        f"{sid}.M{i}",
                        item["text"],
                        f"제거된 페이지 여백({item['kind']}) · PDF {item['page']}쪽",
                        kind="margin",
                    )
                )
            passages = tuple(
                replace(
                    p,
                    text=self.runner.privacy.for_summarizer_text(p.text),
                    location=self.runner.privacy.for_summarizer_text(p.location),
                )
                for p in structure_passages
            )
            overview = Evidence(
                sid,
                structure["path"] + "#structure",
                "\n".join(p.text for p in passages),
                passages=passages,
                question_ids=tuple(structure["question_ids"]),
                counts=tuple(structure["counts"].items()) if structure["complete"] else (),
            )
            if re.search(r"총.*몇|몇.*장|몇.*조문", query):
                evidence.insert(0, overview)
            else:
                evidence.append(overview)
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if web_result is not None and web_result.ok and web_result.data is not None:
            # for 반복문: 대상의 항목을 하나씩 hit에 대입하며 아래 블록을 실행합니다.
            for hit in web_result.data.get("hits", []):
                # add 메서드를 호출해 항목이나 기록을 추가합니다.
                source_ids.add(_canonical_source_url(str(hit.get("url") or "")))
                # datetime.fromisoformat()의 반환값을 fetched_at에 대입합니다.
                fetched_at = datetime.fromisoformat(str(hit["fetched_at"]))
                # 오른쪽 식을 계산한 값을 body에 대입합니다.
                # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
                body = self.runner.privacy.for_summarizer_text(
                    f"{hit.get('title', '')}\n{hit.get('snippet', '')}"
                )
                source_id = f"S{len(evidence) + 1}"
                source = _canonical_source_url(str(hit.get("url") or ""))
                if not source:
                    continue
                evidence.append(
                    Evidence(
                        source_id, source, body, question_ids=tuple(range(1, len(questions) + 1))
                    )
                )
                # 리스트 끝에 항목 하나를 추가합니다.
                envelopes.append(
                    wrap_untrusted_content(
                        source=source,
                        source_id=source_id,
                        source_kind="web",
                        fetched_at=fetched_at,
                        body=body,
                    )
                )

        # source_ids.discard()을 호출해 작업을 수행합니다.
        source_ids.discard("")
        # _status_hint()의 반환값을 status에 대입합니다.
        failed = next((r for r in (doc_result, web_result) if r is not None and not r.ok), None)
        status = _status_hint(failed, source_count=len(source_ids))
        if (
            doc_result
            and doc_result.data
            and doc_result.data.get("diagnostics", {}).get("source_stale")
        ):
            status = "검색 실패"
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return select_evidence(
            ResearchBundle(
                query=query,
                web=web_result,
                docs=doc_result,
                envelopes=tuple(envelopes),
                local_only_hits=tuple(local_only),
                independent_source_count=len(source_ids),
                status_hint=status,
                evidence=tuple(evidence),
                questions=questions if len(questions) > 1 else (),
            ),
            tuple(evidence),
        )


# build_research_context(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: bundle.
# 반환 타입 힌트: 문자열(str).
def build_research_context(bundle: ResearchBundle) -> str:
    # parts에 리스트(순서가 있고 수정 가능)을 대입합니다.
    parts = [f'검색 질의: "{bundle.query}"']
    # 리스트 끝에 항목 하나를 추가합니다.
    parts.append(f"검색 출처 수: {bundle.independent_source_count} (사실성 판단 지표 아님)")
    if bundle.questions:
        parts.append(
            "각 질문에 별도 claim과 question_id를 작성한다. 하나라도 근거가 없으면 insufficient.\n"
            + "\n".join(f"Q{i}: {q}" for i, q in enumerate(bundle.questions, 1))
        )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: bundle.local_only_hits.
    if bundle.local_only_hits:
        # sorted()의 반환값을 paths에 대입합니다.
        paths = sorted({hit.relative_path for hit in bundle.local_only_hits})
        # 리스트 끝에 항목 하나를 추가합니다.
        parts.append(
            "로컬 전용 문서에서 관련 내용을 찾았지만 원문은 외부로 보내지 않습니다: "
            + ", ".join(paths)
        )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: bundle.envelopes.
    if bundle.envelopes:
        # 리스트 끝에 항목 하나를 추가합니다.
        parts.append("다음은 신뢰할 수 없는 검색 결과 데이터입니다.")
        # 반복 가능한 값의 항목들을 리스트 끝에 차례로 추가합니다.
        parts.extend(bundle.envelopes)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: bundle.web is not None and (not
    # bundle.web.ok).
    if bundle.web is not None and not bundle.web.ok:
        # 리스트 끝에 항목 하나를 추가합니다.
        parts.append(f"웹 검색 실패: {bundle.web.error or bundle.web.output}")
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if (
        bundle.docs is not None
        and bundle.docs.ok
        and not bundle.envelopes
        and not bundle.local_only_hits
    ):
        # 리스트 끝에 항목 하나를 추가합니다.
        parts.append("로컬 문서 검색 결과가 없습니다.")
    # 리스트 끝에 항목 하나를 추가합니다.
    parts.append("근거의 내용으로 답변 가능 여부를 판단하세요. 출처 수는 확실성 지표가 아닙니다.")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return "\n\n".join(parts)


# _status_hint(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: web, source_count.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: Literal['확실', '근거 부족', '검색 실패', '결과 없음'].
def select_evidence(bundle: ResearchBundle, evidence: tuple[Evidence, ...]) -> ResearchBundle:
    """The generator and verifier must see exactly the selected source passages."""
    bodies = tuple(
        wrap_untrusted_content(
            source=e.source,
            source_id=e.source_id,
            source_kind="web" if e.source.startswith("http") else "local_doc",
            fetched_at=datetime.now().astimezone(),
            body=evidence_body(e),
        )
        for e in evidence
    )
    return replace(bundle, evidence=evidence, envelopes=bodies)


def evidence_body(e: Evidence) -> str:
    if not e.passages:
        return (e.context + "\n\n" if e.context else "") + e.text
    return json.dumps(
        {
            "passages": [
                {
                    "id": p.id,
                    "text": p.text,
                    "location": p.location,
                    **({"list_size": p.list_size} if p.list_size is not None else {}),
                    **({"kind": p.kind} if p.kind != "body" else {}),
                }
                for p in e.passages
            ],
            "question_ids": e.question_ids,
            "computed_structure_counts": dict(e.counts),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def focus_evidence(bundle: ResearchBundle) -> ResearchBundle:
    """Retain exact matching passages for exhaustive term/period queries.

    This selects answer context only; stored chunks and their embeddings are
    unchanged. Full raw text remains available for exact citation validation.
    """
    query = bundle.query
    margins = [e for e in bundle.evidence if any(p.kind == "margin" for p in e.passages)]
    if margins:
        return select_evidence(
            bundle,
            tuple(
                replace(e, passages=tuple(p for p in e.passages if p.kind == "margin"))
                for e in margins
            ),
        )
    if not broad_question(query):
        return bundle
    if re.search(r"제\d+조(?!\s*(?:외|제외))", query) and not re.search(r"년마다|따라야", query):
        return bundle
    if "년마다" in query:
        terms = ["년마다"]
    elif "따라야" in query:
        terms = ["따라야"]
    else:
        terms = re.findall(r"['\"\u2018\u201c]([^'\"\u2019\u201d]{2,64})['\"\u2019\u201d]", query)
        terms = [t for t in terms if not re.search(r"\s|[()]", t)]
        if not terms:
            terms = re.findall(r"[가-힣]+(?:위원회|장관)", query)
    if not terms:
        return bundle
    focused = []
    for e in bundle.evidence:
        selected = [
            p
            for p in e.passages
            if p.kind == "body" and any(t in re.sub(r"\s+", "", p.text) for t in terms)
        ]
        if not selected:
            continue
        # A selected list premise needs its items, and an item needs its premise.
        scopes = {
            p.scope
            for p in selected
            if p.list_size and ("각 호" in p.text or re.match(r"\d+\.", p.text))
        }
        selected = [
            p for p in e.passages if p in selected or (p.scope in scopes and p.kind == "body")
        ]
        focused.append(replace(e, passages=tuple(selected)))
    return select_evidence(bundle, tuple(focused)) if focused else bundle


def deduplicate_evidence(bundle: ResearchBundle) -> ResearchBundle:
    kept: list[Evidence] = []
    for item in bundle.evidence:
        body = item.text
        document = item.source.split("#chunk=", 1)[0]
        for previous in kept:
            if previous.source.split("#chunk=", 1)[0] != document:
                continue
            if body in previous.text:
                body = ""
                break
            for length in range(min(len(body), len(previous.text)), 15, -1):
                if previous.text.endswith(body[:length]):
                    body = body[length:]
                    break
                if previous.text.startswith(body[-length:]):
                    body = body[:-length]
                    break
        if body.strip():
            kept.append(
                replace(item, text=body, passages=tuple(p for p in item.passages if p.text in body))
            )
    return select_evidence(bundle, tuple(kept))


def _status_hint(
    web: ToolResult | None,
    *,
    source_count: int,
) -> Literal["근거 부족", "검색 실패", "결과 없음"]:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: web is not None and (not web.ok).
    if web is not None and not web.ok:
        # '검색 실패'을 반환하고 이 함수의 실행을 끝냅니다.
        return "검색 실패"
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: source_count == 0.
    if source_count == 0:
        # '결과 없음'을 반환하고 이 함수의 실행을 끝냅니다.
        return "결과 없음"
    return "근거 부족"


def _canonical_source_url(url: str) -> str:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # urlsplit()의 반환값을 parsed에 대입합니다.
        parsed = urlsplit(url.strip())
        # (parsed.hostname or '').lower()의 반환값을 host에 대입합니다.
        host = (parsed.hostname or "").lower()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not host.
        if not host:
            # ''을 반환하고 이 함수의 실행을 끝냅니다.
            return ""
        # 오른쪽 식을 계산한 값을 port에 대입합니다.
        port = parsed.port
    # ValueError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except ValueError:
        # ''을 반환하고 이 함수의 실행을 끝냅니다.
        return ""
    # parsed.scheme.lower()의 반환값을 scheme에 대입합니다.
    scheme = parsed.scheme.lower()
    # 오른쪽 식을 계산한 값을 default_port에 대입합니다.
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    # 오른쪽 식을 계산한 값을 netloc에 대입합니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    netloc = host if port is None or default_port else f"{host}:{port}"
    # 오른쪽 식을 계산한 값을 path에 대입합니다.
    path = parsed.path or "/"
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


# load_tools_prompt(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: 문자열(str).
def load_tools_prompt(path: Path | None = None) -> str:
    # 오른쪽 식을 계산한 값을 prompt_path에 대입합니다.
    prompt_path = path or Path(__file__).with_name("prompts") / "system_tools.md"
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return prompt_path.read_text(encoding="utf-8") + "\n\n" + GENERATION_INSTRUCTION

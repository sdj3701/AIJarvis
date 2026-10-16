"""Generalized regressions; no benchmark question IDs or reference answers."""

import json
from dataclasses import replace

import pytest

from app.rag.document_context import document_context
from app.rag.document_parser import SourceSpan, pdf_to_markdown
from app.rag.grounding import Evidence, ground_answer
from app.rag.passages import make_passages
from tests.unit.test_chunker_indexer import indexer  # noqa: F401

pytestmark = pytest.mark.phase3


def verify(payload):
    n = len(json.loads(payload)["claims"])
    return json.dumps(dict(supported=[True] * n, answers_question=True, conflict=False))


def answer(body, claim, question="규정은?", **kwargs):
    spans = (SourceSpan(0, len(body), 2, "제3장 위원회", "제42조(연구위원회)", "①"),)
    passages = make_passages(body, "S1", spans)
    source = Evidence("S1", "different.pdf#chunk=42", body, passages=passages)
    raw = json.dumps(
        dict(
            status="answered",
            claims=[
                dict(
                    text=claim,
                    citations=[dict(source_id="S1", passage_id=passages[0].id)],
                    **kwargs,
                )
            ],
        )
    )
    return ground_answer(raw, question, (source,), verify)


def test_law_number_and_cross_reference_are_not_citation_locations():
    assert (
        answer(
            "법률 제5987호에 따라 제28조의 기준을 준수한다.",
            "법률 제5987호이며 제28조의 기준을 준수한다.",
        ).reason
        == "passed"
    )
    assert (
        answer("제28조의 기준을 준수한다.", "제29조의 기준을 준수한다.").reason
        == "invalid_location"
    )
    assert (
        answer("제28조의 기준을 준수한다.", "유효기간은 28년이다.").reason == "unsupported_number"
    )


def test_structural_subject_is_allowed_but_other_numeric_facts_are_not():
    assert (
        answer(
            "위원장은 위원 중에서 장관이 지명한다.",
            "연구위원회의 위원장은 장관이 위원 중에서 지명한다.",
            "연구위원회의 위원장은 누가 정하나?",
        ).reason
        == "passed"
    )


def test_request_scope_cannot_replace_mandatory_scope():
    body = (
        "장관은 도지사와 공공기관 또는 단체에 자료를 요청할 수 있다. "
        "이 경우 요청받은 도지사는 사유가 없으면 이에 따라야 한다."
    )
    q = "요청에 반드시 따라야 하는 대상은 누구인가?"
    assert (
        answer(body, "도지사와 공공기관 또는 단체가 따라야 한다.", q).reason
        == "unsupported_duty_scope"
    )
    assert answer(body, "도지사가 사유가 없으면 따라야 한다.", q).reason == "passed"
    joined = (
        "장관은 공공기관 또는 단체에 자료 제출을 요청할 수 있으며, "
        "도지사는 사유가 없으면 이에 따라야 한다."
    )
    assert answer(joined, "공공기관 또는 단체가 따라야 한다.", q).reason == "unsupported_duty_scope"


def test_outline_counts_exclude_supplement_and_reuse_original_chunks(indexer, monkeypatch):  # noqa: F811
    lines = [
        "제1장 총칙",
        "제1조(목적) 공공의 안전을 목적으로 한다.",
        "제2조(정의) 사용하는 용어는 다음과 같다.",
        "1. 관리자는 관리를 담당하는 자이다.",
        "2. 시설은 관리 대상인 장소이다.",
        "제2장 관리",
        "제3조(관리) 관리자는 매년 시설을 검사하여야 한다.",
        "부칙 <제999호,2026. 1. 1.>",
        "제1조(시행일) 공포한 날부터 시행한다.",
    ]
    parsed = pdf_to_markdown(
        [
            dict(
                number=1,
                height=2000,
                lines=[
                    dict(text=t, top=200 + i * 40, bottom=220 + i * 40) for i, t in enumerate(lines)
                ],
            )
        ],
        "fixture",
    )
    monkeypatch.setattr("app.rag.generations.parse_document", lambda *a, **k: parsed)
    ix = replace(
        indexer,
        semantic=None,
        reranker=None,
        settings=indexer.settings.model_copy(
            update={
                "supported_extensions": [".pdf"],
                "chunk_chars": 120,
                "chunk_overlap_chars": 0,
                "semantic": indexer.settings.semantic.model_copy(update={"enabled": False}),
                "rerank": indexer.settings.rerank.model_copy(update={"enabled": False}),
            }
        ),
    )
    (ix.docs_root / "different.pdf").write_bytes(b"fixture")
    assert not ix.sync().errors
    hits = ix.search("관리자")
    expanded, structures = document_context(ix, "전체 몇 장과 몇 조문인가?", hits)
    assert structures[0]["counts"] == {"장": 2, "조문": 3}
    assert structures[0]["complete"]
    assert any(v["size"] == 2 for v in structures[0]["lists"])
    with ix._connection() as db:
        original = {r["chunk_id"]: r["text"] for r in db.execute("SELECT * FROM doc_chunks")}
    assert all(original[h.chunk_id] == h.text for h in expanded)
    ix.last_diagnostics["generation"] = "old-generation"
    assert document_context(ix, "몇 장인가?", hits)[1] == ()
    assert ix.last_diagnostics["source_stale"]


def test_complete_list_count_is_computed_and_cannot_mix_scopes():
    from app.rag.passages import Passage
    from app.rag.structured_answers import count_draft

    scope = ("제1장", "제8조(대상)", "")
    p1 = Passage("S1.a", "1. 시설 관리 업무에 관한 사항", "제8조 1호 · PDF 2쪽", scope, list_size=2)
    p2 = Passage("S1.b", "2. 장비 점검 업무에 관한 사항", "제8조 2호 · PDF 2쪽", scope, list_size=2)
    e = Evidence("S1", "other.pdf#chunk=a", p1.text + "\n\n" + p2.text, passages=(p1, p2))
    draft = count_draft("제8조는 총 몇 개인가?", (e,))
    assert draft is not None and "2개" in draft.claims[0].text
    assert ground_answer(draft.model_dump_json(), "총 몇 개인가?", (e,), verify).reason == "passed"
    assert count_draft("제8조는 총 몇 개인가?", (replace(e, passages=(p1,)),)) is None
    bad = replace(e, passages=(p1, replace(p2, scope=("제2장", "제8조(다른 대상)", ""))))
    assert (
        ground_answer(draft.model_dump_json(), "총 몇 개인가?", (bad,), verify).reason
        == "invalid_calculation"
    )


def test_structure_count_uses_full_outline_and_preserves_units():
    from app.rag.passages import Passage
    from app.rag.structured_answers import count_draft

    p1 = Passage(
        "S1.h", "## 제1장 기본", "제1장 기본 · PDF 1쪽", ("제1장 기본", "", ""), kind="heading"
    )
    p2 = Passage(
        "S1.a",
        "### 제1조(목적)",
        "제1조(목적) · PDF 1쪽",
        ("제1장 기본", "제1조(목적)", ""),
        kind="heading",
    )
    e = Evidence(
        "S1",
        "other.pdf#structure",
        p1.text + "\n" + p2.text,
        passages=(p1, p2),
        counts=(("장", 2), ("조문", 5)),
    )
    d = count_draft("전체 몇 장과 몇 개 본문 조문인가?", (e,))
    assert d is not None
    assert (
        ground_answer(d.model_dump_json(), "전체 몇 장과 몇 개 조문인가?", (e,), verify).reason
        == "passed"
    )
    d.claims[0].calculations[0].unit = "년"
    assert (
        ground_answer(d.model_dump_json(), "전체 몇 장인가?", (e,), verify).reason
        == "invalid_calculation"
    )


def test_parallel_objects_share_subject_and_predicate():
    from app.rag.passages import question_parts

    assert question_parts("관리자는 소관 시설 및 관할 장비를 몇 년마다 검사하나?") == (
        "관리자는 소관 시설를 몇 년마다 검사하나?",
        "관리자는 관할 장비를 몇 년마다 검사하나?",
    )


def test_pdf_only_definition_never_becomes_general_knowledge():
    from app.orchestrator.query_plan import plan_query

    p = plan_query("/search 제공한 문서 PDF만 근거로 답해줘. 기관의 정의는 어느 법률인가?")
    assert p.knowledge_scope == "internal" and p.route == "local_doc"


def test_exhaustive_period_draft_keeps_every_actor_and_modality():
    from app.rag.passages import Passage
    from app.rag.structured_answers import extractive_structure_draft

    passages = (
        Passage("S1.a", "관리자는 4년마다 시설을 검사하여야 한다."),
        Passage("S1.b", "소유자는 7년마다 장비를 교체할 수 있다."),
    )
    e = Evidence("S1", "other.pdf", "\n".join(p.text for p in passages), passages=passages)
    draft = extractive_structure_draft("'년마다' 규정을 모두 비교해 줘", (e,))
    assert draft is not None
    assert [c.text for c in draft.claims] == [p.text for p in passages]
    assert (
        ground_answer(draft.model_dump_json(), "주기 규정을 모두 설명해", (e,), verify).reason
        == "passed"
    )
    assert extractive_structure_draft("검사 주기는?", (e,)) is None


def test_margin_draft_never_treats_footer_as_substantive_provision():
    from app.rag.passages import Passage
    from app.rag.structured_answers import extractive_structure_draft

    p = Passage("S1.m", "자료센터 9", "제거된 페이지 여백(footer) · PDF 9쪽", kind="margin")
    e = Evidence("S1", "other.pdf#structure", p.text, passages=(p,))
    d = extractive_structure_draft("'자료센터' 규정이 포함되나?", (e,))
    assert d is not None and "본문 조문의 규정이 아닙니다" in d.claims[0].text
    assert ground_answer(d.model_dump_json(), "자료센터 규정인가?", (e,), verify).reason == "passed"


def test_duty_repair_extracts_unique_mandatory_subject_only():
    from app.rag.structured_answers import repair_duty_draft

    text = "기관에 요청할 수 있으며, 관리자는 특별한 사유가 없으면 이에 따라야 한다."
    passages = make_passages(text, "S1")
    e = Evidence("S1", "other.pdf", text, passages=passages)
    raw = json.dumps(
        dict(
            status="answered",
            claims=[dict(text="기관이 따라야 한다.", citations=[dict(source_id="S1", quote=text)])],
        )
    )
    d = repair_duty_draft(raw, (e,))
    assert d is not None and d.claims[0].text == "관리자는 특별한 사유가 없으면 이에 따라야 한다."
    assert repair_duty_draft(raw, ()) is None

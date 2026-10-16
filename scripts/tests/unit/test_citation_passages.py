import json

import pytest

from app.rag.document_parser import SourceSpan
from app.rag.grounding import Evidence, ground_answer
from app.rag.passages import make_passages, question_parts

pytestmark = pytest.mark.phase3


def evidence(sid, text, qid, article, page):
    spans = (SourceSpan(0, len(text), page, "제1장 총칙", article, "①"),)
    return Evidence(
        sid, "law.pdf", text, passages=make_passages(text, sid, spans), question_ids=(qid,)
    )


def claim(text, sid, qid=0):
    return {
        "text": text,
        "question_id": qid,
        "citations": [{"source_id": sid, "passage_id": sid + ".P1"}],
    }


def run(claims, evidence, questions=()):
    for c in claims:
        for citation in c["citations"]:
            sid = citation["source_id"]
            if citation["passage_id"] == sid + ".P1":
                citation["passage_id"] = (
                    next(e for e in evidence if e.source_id == sid).passages[0].id
                )
    return ground_answer(
        json.dumps({"status": "answered", "claims": claims}),
        "질문",
        evidence,
        lambda p: json.dumps(
            {
                "supported": [True] * len(json.loads(p)["claims"]),
                "answers_question": True,
                "conflict": False,
            }
        ),
        questions,
    )


def test_exact_id_expands_source_and_renders_article_paragraph_page():
    source = evidence("S1", "계획은 5년마다 수립한다.", 1, "제10조(계획)", 2)
    result = run([claim("계획은 5년마다 수립합니다.", "S1")], (source,))
    assert result.status == "근거 확인"
    assert "제10조(계획) 제1항 · PDF 2쪽" in result.text
    assert "인용: 계획은 5년마다 수립한다." in result.text
    assert run([claim("제 10 조에 따라 5년마다 수립합니다.", "S1")], (source,)).reason == "passed"


def test_wrong_ids_and_rewritten_quotes_are_rejected():
    source = evidence("S1", "계획은 5년마다 수립한다.", 1, "제10조(계획)", 2)
    for edit in ({"passage_id": "S2.P1"}, {"quote": "계획은 ... 수립한다."}):
        c = claim("계획은 5년마다 수립합니다.", "S1")
        c["citations"][0].update(edit)
        assert run([c], (source,)).reason == "invalid_citation"


def test_location_number_cannot_justify_a_fact():
    source = evidence("S1", "계획은 5년마다 수립한다.", 1, "제10조(계획)", 2)
    assert (
        run([claim("계획은 10년마다 수립합니다.", "S1")], (source,)).reason == "unsupported_number"
    )
    assert (
        run([claim("제99조에 따라 5년마다 수립합니다.", "S1")], (source,)).reason
        == "invalid_location"
    )


def test_multi_question_coverage_and_source_binding_even_if_verifier_says_yes():
    sources = (
        evidence("S1", "계획은 5년마다 수립한다.", 1, "제10조(계획)", 2),
        evidence("S2", "보고서는 2년마다 제출한다.", 2, "제15조(보고)", 4),
    )
    qs = ("계획 수립 주기는?", "보고 주기는?")
    assert run([claim("모두 2년입니다.", "S2", 2)], sources, qs).reason == "incomplete_questions"
    assert (
        run(
            [claim("계획은 2년입니다.", "S2", 1), claim("보고는 2년입니다.", "S2", 2)], sources, qs
        ).reason
        == "wrong_question_source"
    )
    result = run(
        [claim("계획은 5년입니다.", "S1", 1), claim("보고는 2년입니다.", "S2", 2)], sources, qs
    )
    assert result.status == "근거 확인"
    assert "PDF 2쪽" in result.text and "PDF 4쪽" in result.text


def test_compound_questions_and_formatting_instruction_are_separate():
    assert question_parts("계획의 주기와 보고 주기는 각각 몇 년인가요?") == (
        "계획의 주기는 몇 년인가요?",
        "보고 주기는 몇 년인가요?",
    )
    assert question_parts(
        "제공한 법 PDF만 근거로 답해줘. 계획 주기는? "
        "근거가 되는 조·항 번호와 PDF 페이지를 답변에 명시해줘."
    ) == ("계획 주기는?",)
    assert len(question_parts("예전 질문? / 그럼 어디서?")) == 1


def test_verifier_receives_selected_quote_not_uncited_neighbor():
    body = "① 계획은 5년마다 수립한다.\n\n② 보고서는 2년마다 제출한다."
    source = evidence("S1", body, 1, "제10조(계획)", 2)
    seen = []

    def verify(payload):
        seen.append(json.loads(payload))
        return '{"supported":[false],"answers_question":false,"conflict":false}'

    draft = {
        "status": "answered",
        "claims": [
            {
                "text": "보고서는 2년마다 제출한다.",
                "citations": [{"source_id": "S1", "passage_id": source.passages[0].id}],
            }
        ],
    }
    # Numeric guard stops this mismatch even before the model verifier.
    assert (
        ground_answer(json.dumps(draft), "보고는?", (source,), verify).reason
        == "unsupported_number"
    )
    draft["claims"][0]["text"] = "보고서를 정기적으로 제출한다."
    assert (
        ground_answer(json.dumps(draft), "보고는?", (source,), verify).reason == "unsupported_claim"
    )
    assert "보고서" not in seen[0]["evidence"][0]["text"]


def test_each_question_is_verified_independently():
    sources = (
        evidence("S1", "계획은 5년마다 수립한다.", 1, "제10조(계획)", 2),
        evidence("S2", "보고서는 2년마다 제출한다.", 2, "제15조(보고)", 4),
    )
    claims = [claim("계획은 5년입니다.", "S1", 1), claim("보고는 2년입니다.", "S2", 2)]
    for c, e in zip(claims, sources, strict=True):
        c["citations"][0]["passage_id"] = e.passages[0].id
    seen = []

    def verify(payload):
        seen.append(json.loads(payload))
        return json.dumps(
            {"supported": [len(seen) == 1], "answers_question": True, "conflict": False}
        )

    result = ground_answer(
        json.dumps({"status": "answered", "claims": claims}),
        "복합 질문",
        sources,
        verify,
        ("계획은?", "보고는?"),
    )
    assert result.reason == "unsupported_claim" and not result.sources
    assert [p["question"] for p in seen] == ["계획은?", "보고는?"]


def test_markdown_heading_without_blank_line_keeps_body():
    text = "# 제목\n신청은 인사 포털에서 합니다.\n## 다음 제목\n기한은 3일 전입니다."
    passages = make_passages(text, "S1")
    assert [p.text for p in passages] == ["신청은 인사 포털에서 합니다.", "기한은 3일 전입니다."]


def test_followup_verifies_current_question_with_separate_user_context():
    source = evidence("S1", "연차는 인사 포털에서 신청합니다.", 1, "제1조(신청)", 1)
    seen = []

    def verify(payload):
        seen.append(json.loads(payload))
        return '{"supported":[true],"answers_question":true,"conflict":false}'

    draft = {
        "status": "answered",
        "claims": [
            {
                "text": "인사 포털에서 신청합니다.",
                "citations": [{"source_id": "S1", "passage_id": source.passages[0].id}],
            }
        ],
    }
    result = ground_answer(
        json.dumps(draft), "연차 기한은? / 그럼 어디에서 신청해?", (source,), verify
    )
    assert result.reason == "passed"
    assert seen[0]["question"] == "그럼 어디에서 신청해?"
    assert seen[0]["previous_user_context"] == "연차 기한은?"


def test_named_query_subject_cannot_borrow_sibling_quote_even_if_model_agrees():
    body = "청록도면을 위조하면 처벌한다.\n\n주황기록을 위조하면 처벌한다."
    source = evidence("S1", body, 1, "제1조(벌칙)", 1)
    draft = {
        "status": "answered",
        "claims": [
            {
                "text": "주황기록을 위조하면 처벌한다.",
                "citations": [{"source_id": "S1", "passage_id": source.passages[0].id}],
            }
        ],
    }
    result = ground_answer(
        json.dumps(draft),
        "주황기록의 위조는?",
        (source,),
        lambda _: '{"supported":[true],"answers_question":true,"conflict":false}',
    )
    assert result.reason == "uncited_query_subject" and not result.sources


def test_list_citation_includes_supplied_parent_from_same_article():
    head = "위원회는 다음 각 호의 사항을 심의한다."
    item = "7. 건축에 관한 조사 및 연구에 관한 사항"
    from app.rag.passages import Passage

    sources = (
        Evidence(
            "S1",
            "law.pdf#chunk=tail",
            item,
            passages=(
                Passage("S1.item", item, "제14조(기능) 7호 · PDF 4쪽", ("제4장", "제14조", "")),
            ),
        ),
        Evidence(
            "S2",
            "law.pdf#chunk=head",
            head,
            passages=(Passage("S2.head", head, "제14조(기능) · PDF 3쪽", ("제4장", "제14조", "")),),
        ),
    )
    draft = {
        "status": "answered",
        "claims": [
            {
                "text": "위원회는 건축 조사 및 연구를 심의한다.",
                "citations": [{"source_id": "S1", "passage_id": "S1.item"}],
            }
        ],
    }
    seen = []

    def verify(payload):
        seen.append(json.loads(payload))
        return '{"supported":[true],"answers_question":true,"conflict":false}'

    result = ground_answer(json.dumps(draft), "무엇을 심의하나?", sources, verify)
    assert result.reason == "passed"
    assert head in result.text and item in result.text
    assert "PDF 3쪽" in result.text and "PDF 4쪽" in result.text
    assert len(seen[0]["claims"][0]["citations"]) == 2

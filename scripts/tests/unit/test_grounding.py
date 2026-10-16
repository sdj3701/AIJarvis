"""Fail-closed citations and claim checks, independent of model quality."""
import json

import pytest

from app.rag.grounding import Evidence, ground_answer

pytestmark = pytest.mark.phase3

SOURCE = Evidence("S1", "leave.md#chunk=leave", "연차는 3일 전에 신청합니다.")


def candidate(text="연차는 3일 전에 신청합니다.", quote=None, source_id="S1"):
    return json.dumps({"status": "answered", "claims": [{
        "text": text, "citations": [{"source_id": source_id,
                                      "quote": quote or SOURCE.text}],
    }]}, ensure_ascii=False)


def approve(payload):
    assert SOURCE.text in payload
    return '{"supported": [true], "answers_question": true, "conflict": false}'


def test_one_source_is_enough_but_never_called_certain():
    answer = ground_answer(candidate(), "연차 신청 기한?", (SOURCE,), approve)
    assert answer.status == "근거 확인"
    assert "확실" not in answer.text
    assert SOURCE.source in answer.text
    assert answer.sources == (SOURCE.source,)


@pytest.mark.parametrize("raw", [
    candidate(source_id="S999"), candidate(quote="연차는 10일 전에 신청합니다."),
    candidate(text="연차는 10일 전에 신청합니다."),
    '{"status":"answered","claims":[]}', "임의 답변 [1]\n상태: 확실",
    '{"status":"answered","claims":[],"url":"https://invented.example"}',
])
def test_invalid_citation_or_claim_never_reaches_verifier(raw):
    def forbidden(_):
        raise AssertionError("Verifier must not run")
    answer = ground_answer(raw, "연차 신청 기한?", (SOURCE,), forbidden)
    assert answer.status == "근거 부족"
    assert answer.sources == ()
    assert "10일" not in answer.text


@pytest.mark.parametrize("verdict", [
    '{"supported":[false],"answers_question":true,"conflict":false}',
    '{"supported":[true],"answers_question":false,"conflict":false}',
    '{"supported":[],"answers_question":true,"conflict":false}',
    '{"supported":["true"],"answers_question":true,"conflict":false}',
    'not json',
])
def test_unsupported_or_invalid_verification_abstains(verdict):
    answer = ground_answer(candidate(), "연차 신청 기한?", (SOURCE,), lambda _: verdict)
    assert answer.status == "근거 부족"
    assert "연차는 3일" not in answer.text


def test_conflict_never_returns_a_decisive_answer():
    answer = ground_answer(candidate(), "연차 신청 기한?", (SOURCE,), lambda _: (
        '{"supported":[true],"answers_question":true,"conflict":true}'
    ))
    assert answer.status == "상충"
    assert answer.sources == ()


def test_verifier_outage_abstains():
    def unavailable(_):
        raise TimeoutError()
    answer = ground_answer(candidate(), "연차 신청 기한?", (SOURCE,), unavailable)
    assert answer.status == "근거 부족"
    assert answer.reason == "verifier_unavailable"


def test_two_irrelevant_sources_do_not_create_confidence():
    answer = ground_answer('{"status":"insufficient","claims":[]}', "연봉?",
                           (SOURCE, Evidence("S2", "food.md", "파스타")), approve)
    assert answer.status == "근거 부족"


def test_citations_only_allow_exact_quote_except_whitespace():
    answer = ground_answer(candidate(quote="연차는 3일\n전에 신청합니다."),
                           "연차 신청 기한?", (SOURCE,), approve)
    assert answer.status == "근거 확인"


def test_thousands_separator_is_not_a_new_fact():
    source = Evidence("S1", "expense.md", "출장 식비는 30000원입니다.")
    raw = candidate(text="출장 식비는 30,000원입니다.", quote=source.text)
    answer = ground_answer(raw, "식비?", (source,), lambda _: (
        '{"supported":[true],"answers_question":true,"conflict":false}'
    ))
    assert answer.status == "근거 확인"

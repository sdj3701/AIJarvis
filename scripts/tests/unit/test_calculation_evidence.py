import json

import pytest

from app.rag.grounding import Evidence, ground_answer

pytestmark = pytest.mark.phase3


def check(text, quotes, operation, values, result, unit):
    evidence = [Evidence(f"S{i}", f"doc{i}", quote) for i, quote in enumerate(quotes)]
    calculation = {
        "operation": operation,
        "operands": [
            {"value": v, "unit": u, "citation_index": i} for i, (v, u) in enumerate(values)
        ],
        "result": result,
        "unit": unit,
    }
    raw = json.dumps(
        {
            "status": "answered",
            "claims": [
                {
                    "text": text,
                    "citations": [{"source_id": e.source_id, "quote": e.text} for e in evidence],
                    "calculations": [calculation],
                }
            ],
        },
        ensure_ascii=False,
    )
    return ground_answer(
        raw,
        "계산해줘",
        evidence,
        lambda _: '{"supported":[true],"answers_question":true,"conflict":false}',
    )


@pytest.mark.parametrize("result,expected", [("50000", "근거 확인"), ("60000", "근거 부족")])
def test_sum_requires_recomputation(result, expected):
    answer = check(
        f"합계는 {result}원입니다.",
        ["식비는 20000원입니다.", "교통비는 30000원입니다."],
        "add",
        [("20000", "원"), ("30000", "원")],
        result,
        "원",
    )
    assert answer.status == expected


def test_unit_mismatch_and_uncited_operand_are_rejected():
    for values in [[("20000", "원"), ("30000", "달러")], [("20001", "원"), ("30000", "원")]]:
        answer = check(
            "합계는 50000원입니다.",
            ["식비는 20000원입니다.", "교통비는 30000원입니다."],
            "add",
            values,
            "50000",
            "원",
        )
        assert answer.reason == "invalid_calculation"


def test_supported_conversion_and_unsupported_currency_conversion():
    assert (
        check(
            "거리는 2000m입니다.", ["총 거리는 2km입니다."], "convert", [("2", "km")], "2000", "m"
        ).status
        == "근거 확인"
    )
    assert (
        check(
            "가격은 2000원입니다.",
            ["가격은 2달러입니다."],
            "convert",
            [("2", "달러")],
            "2000",
            "원",
        ).reason
        == "invalid_calculation"
    )


def test_date_requires_cited_base_and_calendar_days():
    assert (
        check(
            "마감은 2026-10-17입니다.",
            ["시작 날짜는 2026-10-14입니다.", "기간은 3일입니다."],
            "date_add",
            [("2026-10-14", "date"), ("3", "일")],
            "2026-10-17",
            "date",
        ).status
        == "근거 확인"
    )
    assert (
        check(
            "마감은 2026-10-17입니다.",
            ["시작 날짜는 미정입니다.", "기간은 3일입니다."],
            "date_add",
            [("2026-10-14", "date"), ("3", "일")],
            "2026-10-17",
            "date",
        ).reason
        == "invalid_calculation"
    )


def test_business_day_and_unit_conversion_cannot_be_smuggled_as_date_add():
    result = check(
        "마감은 2026-10-17입니다.",
        ["시작 날짜는 2026-10-14입니다.", "기간은 3영업일입니다."],
        "date_add",
        [("2026-10-14", "date"), ("3", "일")],
        "2026-10-17",
        "date",
    )
    assert result.status == "근거 부족"


def test_negative_result_is_not_accepted_as_positive():
    assert (
        check(
            "잔액은 -10000원입니다.",
            ["예산은 20000원입니다.", "지출은 30000원입니다."],
            "subtract",
            [("20000", "원"), ("30000", "원")],
            "10000",
            "원",
        ).reason
        == "invalid_calculation"
    )

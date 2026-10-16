import pytest

from app.llm.base import Message
from app.orchestrator.query_plan import plan_query

pytestmark = pytest.mark.phase3


@pytest.mark.parametrize(
    "query",
    [
        "출장 식비 한도가 얼마야?",
        "출장 식비 한도 알려줘",
        "재택근무 승인 절차는?",
        "우리 회사 재택근무 승인 절차는?",
        "최신 사내 출장 규정 찾아줘",
    ],
)
def test_internal_paraphrases_stay_local(query):
    plan = plan_query(query)
    assert plan.route == "local_doc"
    assert plan.knowledge_scope == "internal"


def test_followup_uses_user_context_not_assistant_claims():
    history = [
        Message("user", "우리 회사 연차 신청 규정 알려줘"),
        Message("assistant", "잘못된 주장: 999일 전에 신청하세요"),
    ]
    plan = plan_query("그럼 며칠 전에 신청하면 돼?", history)
    assert plan.route == "local_doc"
    assert "연차" in plan.search_query
    assert "999" not in plan.search_query
    assert plan.context_refs == (0,)


@pytest.mark.parametrize(
    "history", [[], [Message("user", "연차와 병가 규정 알려줘")], [Message("user", "고마워")]]
)
def test_missing_or_ambiguous_reference_needs_clarification(history):
    assert plan_query("그럼 언제까지?", history).route == "clarify"


@pytest.mark.parametrize(
    "query", ["안녕", "고마워", "/open_app discord", "/clear", "취소", "내일 일정 요약해줘"]
)
def test_non_research_routes_are_preserved(query):
    assert plan_query(query).route == "general"


def test_external_intent_and_internal_followup():
    assert plan_query("웹 최신 Ollama 소식").route == "web"
    p = plan_query("그럼 최신 내용은?", [Message("user", "사내 연차 규정 알려줘")])
    assert p.route == "local_doc"

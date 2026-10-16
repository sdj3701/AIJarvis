"""Pure retrieval planning. Only user utterances can supply missing context.

This is an explicit, conservative routing policy, not a semantic classifier.
It deliberately keeps ambiguous private questions away from external search.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.llm.base import Message

INTERNAL = re.compile(
    r"회사|사내|내부|로컬|우리\s|내가|내\s|계약|사번|연락처|전화번호|"
    r"연차|휴가|병가|취업규칙|인사\s*규정|출장|식비|숙박비|재택근무|복지|결재|보안\s*규정"
)
WEB = re.compile(r"웹|인터넷|뉴스|날씨|최신|https?://", re.I)
FOLLOWUP = re.compile(
    r"^(?:그럼|그러면|그건|그거|그것|거기|그때|이건|이거|그\s*(?:규정|경우|문서))"
)
QUESTION = re.compile(
    r"[?\uff1f]|얼마|언제|어떻게|무엇|뭐야|뭔가|왜\s|누가|몇\s|며칠|"
    r"알려\s*줘|설명|검색|찾아\s*줘|차이|비교|요약|인가요|나요$|는지|search\s",
    re.I,
)
SMALLTALK = re.compile(r"^(?:안녕(?:하세요)?|고마워|감사합니다|좋아|네|응|취소|아니오)[.!?\s]*$")
_TOPICS = (r"연차|휴가", r"병가", r"출장|식비|숙박", r"재택근무", r"급여|연봉")
GENERAL_KNOWLEDGE = re.compile(
    r"일반\s*(?:지식|적인)|개념|정의|원리|차이|광합성|중력|레시피|요리법|"
    r"\bRAG\b|트랜스포머|신경망|뉴럴|파이썬",
    re.I,
)


@dataclass(frozen=True, slots=True)
class QueryPlan:
    original_query: str
    search_query: str
    route: Literal["local_doc", "web", "general", "clarify"]
    knowledge_scope: Literal["internal", "general", "unknown"]
    context_refs: tuple[int, ...] = ()
    reason: str = "direct"


def plan_query(text: str, history: Sequence[Message] = ()) -> QueryPlan:
    original = text.strip()
    explicit = bool(re.match(r"^/search(?:\s|$)", original, re.I))
    query = re.sub(r"^/search\s*", "", original, flags=re.I) if explicit else original
    if (original.startswith("/") and not explicit) or SMALLTALK.fullmatch(query):
        return QueryPlan(original, query, "general", "unknown", reason="non_research")
    if (
        not explicit
        and re.search(r"일정.*(?:요약|보여|확인)", query)
        and not INTERNAL.search(query)
    ):
        return QueryPlan(original, query, "general", "unknown", reason="calendar_action")
    refs: tuple[int, ...] = ()
    if FOLLOWUP.search(query):
        # Stop at the last user turn; do not bridge a changed topic or use an AI answer.
        users = [(i, m.content) for i, m in enumerate(history) if m.role == "user"]
        if not users or not (QUESTION.search(users[-1][1]) or INTERNAL.search(users[-1][1])):
            return QueryPlan(original, query, "clarify", "unknown", reason="missing_context")
        anchor_index, anchor = users[-1]
        topics = sum(bool(re.search(pattern, anchor)) for pattern in _TOPICS)
        if topics > 1 and not INTERNAL.search(query):
            return QueryPlan(original, query, "clarify", "unknown", reason="ambiguous_context")
        context = [(anchor_index, anchor)]
        # Follow a short chain of follow-ups, never copying assistant facts.
        for i, previous in reversed(users[-4:-1]):
            if not FOLLOWUP.search(context[0][1]):
                break
            context.insert(0, (i, previous))
        if FOLLOWUP.search(context[0][1]) or sum(len(s) for _, s in context) > 1600:
            return QueryPlan(original, query, "clarify", "unknown", reason="unresolved_context")
        refs = tuple(i for i, _ in context)
        query = " / ".join(re.sub(r"^/search\s*", "", s) for _, s in context) + " / " + query
    internal = bool(INTERNAL.search(query))
    document_only = bool(
        re.search(
            r"(?:PDF|문서|자료|원문)(?:만|\s*에\s*있는|\s*내용).*?(?:근거|기준|답)|제공한.*(?:PDF|문서)|이\s*법(?:에서|\(|은)",
            query,
            re.I,
        )
    )
    scope: Literal["internal", "general", "unknown"] = (
        "internal"
        if internal or document_only
        else "general"
        if GENERAL_KNOWLEDGE.search(query) or WEB.search(query)
        else "unknown"
    )
    if WEB.search(query) and not internal and not document_only:
        route: Literal["local_doc", "web", "general", "clarify"] = "web"
    elif explicit or refs or internal or QUESTION.search(query):
        route = "local_doc"
    else:
        route = "general"
    return QueryPlan(original, query, route, scope, refs, "user_context" if refs else "direct")

"""Deterministic drafts for narrow structural counts, still source-verified."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.rag.grounding import Calculation, Citation, Claim, Draft, Evidence, Operand
from app.rag.passages import Passage


def extractive_structure_draft(query: str, evidence: Sequence[Evidence]) -> Draft | None:
    """Avoid dropping source clauses in narrowly identifiable exhaustive queries."""
    margins = [(e, p) for e in evidence for p in e.passages if p.kind == "margin"]
    if margins and all(p.kind == "margin" for e in evidence for p in e.passages):
        if len(margins) > 16:
            return None
        labels = ", ".join(dict.fromkeys(p.text for _, p in margins))
        text = f"{labels}는 PDF 페이지 여백의 머리말·꼬리말이며, 본문 조문의 규정이 아닙니다."
        if len(text) > 500:
            return None
        return Draft(
            status="answered",
            claims=[
                Claim(
                    text=text,
                    citations=[
                        Citation(source_id=e.source_id, passage_id=p.id) for e, p in margins
                    ],
                )
            ],
        )
    if "년마다" not in query or not re.search(r"모두|전체", query):
        return None
    selected = [
        (e, p)
        for e in evidence
        for p in e.passages
        if p.kind == "body" and re.search(r"\d+\s*년마다", p.text)
    ]
    if not selected or len(selected) > 16:
        return None
    claims = []
    for e, p in selected:
        text = re.sub(r"<[^>]*>", "", p.text).strip()
        if len(text) > 500:
            return None
        claims.append(
            Claim(text=text, citations=[Citation(source_id=e.source_id, passage_id=p.id)])
        )
    return Draft(status="answered", claims=claims)


def repair_duty_draft(raw: str, evidence: Sequence[Evidence]) -> Draft | None:
    """Extract a uniquely identified mandatory clause after a scope rejection.

    No new evidence or interpretation is added. The normal verifier must still
    approve this exact source-bound draft before it can be displayed.
    """
    try:
        draft = Draft.model_validate_json(raw)
    except ValueError:
        return None
    if len(draft.claims) != 1:
        return None
    original = draft.claims[0]
    found = []
    for c in original.citations:
        source = next((e for e in evidence if e.source_id == c.source_id), None)
        if source is None:
            continue
        for p in source.passages:
            if p.id != c.passage_id and re.sub(r"\s+", "", p.text) != re.sub(r"\s+", "", c.quote):
                continue
            for m in re.finditer(
                r"(?:이\s*경우|있으며\s*,|있고\s*,)\s*([^.]*(?:은|는)\s+[^.]*?따라야\s*한다)",
                p.text,
                re.S,
            ):
                found.append((m[1], source, p))
    unique = {re.sub(r"\s+", "", v[0]): v for v in found}
    if len(unique) != 1:
        return None
    text, source, passage = next(iter(unique.values()))
    return Draft(
        status="answered",
        claims=[
            Claim(
                text=text + ".",
                question_id=original.question_id,
                citations=[Citation(source_id=source.source_id, passage_id=passage.id)],
            )
        ],
    )


def count_draft(query: str, evidence: Sequence[Evidence]) -> Draft | None:
    if not re.search(r"몇\s*(?:개|가지)|몇.*장", query) or re.search(r"비교|각각|나열|설명", query):
        return None
    if re.search(r"몇.*장", query) and "조문" in query:
        sources = [e for e in evidence if dict(e.counts).get("장") and dict(e.counts).get("조문")]
        if len(sources) != 1:
            return None
        e = sources[0]
        claims = []
        for unit in ("장", "조문"):
            number = dict(e.counts)[unit]
            candidates = [
                p
                for p in e.passages
                if p.kind == "heading"
                and len(p.scope) == 3
                and not p.scope[0].startswith("부칙")
                and (bool(p.scope[1]) == (unit == "조문"))
            ]
            if not candidates:
                return None
            claims.append(
                Claim(
                    text=f"부칙을 제외한 본문은 총 {number}{unit}입니다.",
                    citations=[Citation(source_id=e.source_id, passage_id=candidates[0].id)],
                    calculations=[
                        Calculation(
                            operation="count_structure",
                            operands=[Operand(value=str(number), unit=unit, citation_index=0)],
                            result=str(number),
                            unit=unit,
                        )
                    ],
                )
            )
        return Draft(status="answered", claims=claims)
    requested = set(re.findall(r"제\d+조(?:의\d+)?", query))
    if len(requested) != 1:
        return None
    article = next(iter(requested))
    groups: dict[tuple[str, tuple[str, ...], int], dict[int, tuple[Evidence, Passage]]] = {}
    for e in evidence:
        for p in e.passages:
            item = re.match(r"(\d+)\.\s", p.text)
            if (
                not item
                or len(p.scope) != 3
                or not p.scope[1].startswith(article + "(")
                or not p.list_size
            ):
                continue
            key = (e.source.split("#", 1)[0], p.scope, p.list_size)
            groups.setdefault(key, {})[int(item[1])] = (e, p)
    if len(groups) != 1:
        return None
    (_, scope, size), items = next(iter(groups.items()))
    if size > 16 or sorted(items) != list(range(1, size + 1)):
        return None
    citations = [
        Citation(source_id=items[i][0].source_id, passage_id=items[i][1].id)
        for i in range(1, size + 1)
    ]
    calculation = Calculation(
        operation="count_items",
        operands=[
            Operand(value=str(i), unit="호", citation_index=i - 1) for i in range(1, size + 1)
        ],
        result=str(size),
        unit="개",
    )
    return Draft(
        status="answered",
        claims=[
            Claim(
                text=f"{scope[1]}의 항목은 총 {size}개입니다.",
                citations=citations,
                calculations=[calculation],
            )
        ],
    )

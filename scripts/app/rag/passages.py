"""Exact extractive citation units; location labels are application data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256

from app.rag.document_parser import SourceSpan


@dataclass(frozen=True)
class Passage:
    id: str
    text: str
    location: str = ""
    scope: tuple[str, ...] = ()
    list_size: int | None = None
    kind: str = "body"


def make_passages(
    text: str, source_id: str, spans: tuple[SourceSpan, ...] = (), *, include_headings: bool = False
) -> tuple[Passage, ...]:
    result: list[Passage] = []
    # Exclude heading LINES, not their following body when no blank line exists.
    pattern = r"^(?![ \t]*#{1,6}(?:[ \t]|$))[^\n]+(?:\n(?!\n|[ \t]*#{1,6}[ \t])[^\n]+)*"
    blocks = list(re.finditer(pattern, text, re.M))
    if include_headings and spans:
        blocks += list(re.finditer(r"^#{2,3} +(?:제\d+[장조]|부칙)[^\n]*", text, re.M))
    for block in sorted(blocks, key=lambda b: b.start()):
        # IDs select exact contiguous source slices; no ellipsis or rewriting.
        for start in range(block.start(), block.end(), 780):
            end = min(start + 780, block.end())
            body = text[start:end]
            heading = body.startswith("#")
            if len(re.sub(r"\s+", "", body)) < (4 if heading else 8):
                continue
            located = [
                s
                for s in spans
                if s.start < end
                and s.end > start
                and text[max(start, s.start) : min(end, s.end)].strip()
            ]
            labels = []
            for s in located:
                paragraph = (
                    f"제{ord(s.paragraph) - ord('①') + 1}항"
                    if len(s.paragraph) == 1 and "①" <= s.paragraph <= "⑳"
                    else s.paragraph
                )
                label = " ".join(
                    x
                    for x in (
                        "부칙" if s.chapter.startswith("부칙") else "",
                        s.article,
                        paragraph,
                        s.item,
                    )
                    if x
                )
                if label and label not in labels:
                    labels.append(label)
            pages = sorted({s.page for s in located})
            location = " / ".join(labels)
            if pages:
                location += " · PDF " + ", ".join(map(str, pages)) + "쪽"
            identifier = sha256(f"{start}:{body}".encode()).hexdigest()[:8]
            scopes = {(s.chapter, s.article, s.paragraph) for s in located if s.article}
            scope = next(iter(scopes)) if len(scopes) == 1 else ()
            result.append(
                Passage(
                    f"{source_id}.{identifier}",
                    body,
                    location,
                    scope,
                    kind="heading" if heading else "body",
                )
            )
    return tuple(result)


def clean_search_query(text: str) -> str:
    """Remove presentation boilerplate only; keep substantive question clauses."""
    text = re.sub(r"^제공한\s+.+?PDF만\s+근거로\s+답해\s*줘[.]?\s*", "", text)
    text = re.sub(
        r"근거(?:가 되는)?\s*조[·ㆍ]?항\s*번호와\s*PDF\s*페이지를\s*답변에\s*명시해\s*줘[.]?",
        "",
        text,
    )
    return text.strip()


def question_parts(text: str) -> tuple[str, ...]:
    text = clean_search_query(text)
    if " / " in text:
        return (text,)  # User-history chain is one contextual follow-up.
    coordinated = re.fullmatch(r"(.+?(?:은|는))\s+(.+?)\s+및\s+(.+?)(을|를)\s+(.+)", text)
    if coordinated:
        subject, first, second, particle, predicate = coordinated.groups()
        return (
            f"{subject} {first}{particle} {predicate}",
            f"{subject} {second}{particle} {predicate}",
        )
    match = re.fullmatch(r"(.+?)(?:와|과)\s+(.+?)(?:은|는)\s+(각각\s*.+)", text)
    if match:
        predicate = match[3].removeprefix("각각").strip()
        return (match[1] + "는 " + predicate, match[2] + "는 " + predicate)
    parts = tuple(s.strip() + "?" for s in text.split("?") if s.strip())
    return parts if 1 < len(parts) <= 4 else (text,)

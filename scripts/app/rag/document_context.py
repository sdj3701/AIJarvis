"""Bounded read-only legal document views over the current indexed snapshot.

No answers or corpus-specific names are stored here. Original chunk IDs, text and
offsets are retained. Outline counts come from the complete parsed document, not
from a top-k result or from the language model.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from app.rag.document_parser import ParsedDocument
from app.rag.models import RetrievedChunk

if TYPE_CHECKING:
    from app.rag.indexer import DocumentIndexer


def _article_id(text: str) -> str:
    match = re.match(r"제\d+조(?:의\d+)?", text)
    return match[0] if match else ""


def broad_question(query: str) -> bool:
    return bool(re.search(r"모두|전체|총\s*몇|비교|각각|몇\s*개|몇\s*가지|\d+가지", query))


def document_context(
    indexer: DocumentIndexer, query: str, hits: tuple[RetrievedChunk, ...]
) -> tuple[tuple[RetrievedChunk, ...], tuple[dict[str, Any], ...]]:
    if not hits or not hits[0].relative_path.lower().endswith(".pdf"):
        return hits, ()
    doc_id = hits[0].doc_id
    with indexer._connection() as db:
        db.execute("BEGIN")
        active = db.execute("SELECT active_generation FROM rag_index_state").fetchone()
        if active and active[0] != indexer.last_diagnostics.get("generation"):
            indexer.last_diagnostics["source_stale"] = True
            return hits, ()
        source = db.execute(
            """SELECT d.path,d.transfer_class,c.metadata,c.markdown,c.source_hash FROM documents d
            JOIN rag_document_content c USING(doc_id) WHERE doc_id=?""",
            (doc_id,),
        ).fetchone()
        if source is None:
            return hits, ()
        parsed = ParsedDocument.from_snapshot(
            {
                **json.loads(source["metadata"]),
                "markdown": source["markdown"],
                "source_hash": source["source_hash"],
            }
        )
        if not parsed.spans:
            return hits, ()
        rows = db.execute(
            """SELECT c.*,p.title,s.pages,s.structure FROM doc_chunks c
            JOIN rag_chunk_provenance p USING(chunk_id)
            JOIN rag_chunk_structure s USING(chunk_id) WHERE doc_id=? ORDER BY ordinal""",
            (doc_id,),
        ).fetchall()
        if len(rows) > 2048:
            return hits, ()
    all_hits = []
    old = {h.chunk_id: h for h in hits}
    for row in rows:
        start, end = row["start_char"], row["end_char"]
        if row["text"] != parsed.markdown[start:end]:
            indexer.last_diagnostics["source_stale"] = True
            return hits, ()
        spans = tuple(
            {**asdict(s), "start": max(start, s.start) - start, "end": min(end, s.end) - start}
            for s in parsed.spans
            if s.start < end and s.end > start
        )
        original = old.get(row["chunk_id"])
        all_hits.append(
            RetrievedChunk(
                chunk_id=row["chunk_id"],
                doc_id=doc_id,
                relative_path=source["path"],
                ordinal=row["ordinal"],
                text=row["text"],
                start_char=start,
                end_char=end,
                transfer_class=source["transfer_class"],
                score=original.score if original else 0,
                rerank_score=original.rerank_score if original else None,
                title=row["title"],
                pages=tuple(json.loads(row["pages"])),
                structure=tuple(json.loads(row["structure"])),
                spans=spans,
            )
        )
    is_broad = broad_question(query)
    limit = (
        indexer.settings.max_structured_chunks
        if is_broad
        else indexer.settings.max_chunks_per_answer
    )
    ordered: list[RetrievedChunk] = []

    def add(items: Iterable[RetrievedChunk]) -> None:
        for h in items:
            if h.chunk_id not in {v.chunk_id for v in ordered}:
                ordered.append(h)

    def articles(hit: RetrievedChunk) -> set[tuple[str, str]]:
        return {(str(s["chapter"]), str(s["article"])) for s in hit.spans if s["article"]}

    # Explicit structure references precede statistical similarity. An excluded
    # article is not boosted; supplementary provisions have a separate namespace.
    excluded = set(re.findall(r"(제\s*\d+조)\s*(?:외|제외)", query))
    requested = set(re.findall(r"제\s*\d+조(?:의\d+)?", query)) - excluded
    supplement = "부칙" in query

    def exact_article(hit: RetrievedChunk) -> bool:
        return any(
            _article_id(a) in requested and ch.startswith("부칙") == supplement
            for ch, a in articles(hit)
        )

    if requested:
        add(h for h in all_hits if exact_article(h))
    chapter = re.search(r"제\s*\d+장", query)
    if chapter:
        add(h for h in all_hits if any(str(s["chapter"]).startswith(chapter[0]) for s in h.spans))
    if is_broad:
        terms = re.findall(r"['\"\u2018\u201c]([^'\"\u2019\u201d]{2,64})['\"\u2019\u201d]", query)
        terms += re.findall(r"[가-힣]+(?:위원회|장관)", query)
        if "따라야" in query:
            terms.append("따라야")
        if "년마다" in query:
            terms.append("년마다")
        matches = [
            h
            for h in all_hits
            if any(
                t in re.sub(r"\s+", "", h.text)
                for t in terms
                if " " not in t and not t.startswith("n")
            )
        ]
        add(matches)
    add(hits[:1])
    # Fetch every fragment of the winning article before unrelated neighbors.
    parent_articles = articles(hits[0])
    add(h for h in all_hits if articles(h) & parent_articles)
    if is_broad:
        add(hits)
    if re.search(r"참조|따른|경미|생략|경우|조건", query):
        references = set()
        for h in ordered[:3]:
            for match in re.finditer(r"제\d+조(?:의\d+)?", h.text):
                # Do not resolve a citation to a different law against this PDF.
                prefix = h.text[max(0, match.start() - 80) : match.start()]
                if "」" in prefix and not re.search(r"[.。]\s*[^.。]*$", prefix):
                    continue
                references.add(match[0])
        add(
            h
            for h in all_hits
            if any(
                _article_id(a) in references and not ch.startswith("부칙") for ch, a in articles(h)
            )
        )
    add(hits)
    if excluded:
        ordered = [
            h
            for h in ordered
            if not any(
                _article_id(a) in excluded and not ch.startswith("부칙") for ch, a in articles(h)
            )
        ]
    selected = tuple(ordered[:limit])
    # Whole-document numbered list cardinality, keyed by chapter/article/paragraph.
    list_items: dict[tuple[str, str, str], set[str]] = {}
    for span in parsed.spans:
        if span.item:
            list_items.setdefault((span.chapter, span.article, span.paragraph), set()).add(
                span.item
            )
    lists = [dict(scope=list(key), size=len(value)) for key, value in list_items.items()]
    outline = []
    for m in re.finditer(r"^#{2,3} +(.+)$", parsed.markdown, re.M):
        located = [
            s
            for s in parsed.spans
            if s.start < m.end()
            and s.end > m.start()
            and parsed.markdown[max(m.start(), s.start) : min(m.end(), s.end)].strip()
        ]
        if not located:
            continue
        span = located[0]
        outline.append(
            dict(
                text=m[0],
                start=m.start(),
                end=m.end(),
                pages=sorted({s.page for s in located}),
                chapter=span.chapter,
                article=span.article,
                kind="article" if m[0].startswith("### ") else "chapter",
            )
        )
    chapters = {s.chapter for s in parsed.spans if re.match(r"제\d+장\s", s.chapter)}
    article_ids = {
        (s.chapter, s.article)
        for s in parsed.spans
        if s.article and not s.chapter.startswith("부칙")
    }
    inspect_margins = bool(re.search(r"여백|머리말|꼬리말|문장\s*중간|규정이\s*포함|제거", query))
    margin_terms = re.findall(
        r"['\"\u2018\u201c]([^'\"\u2019\u201d]{2,64})['\"\u2019\u201d]", query
    )
    removed = [
        item
        for item in parsed.removed
        if inspect_margins and any(term in str(item.get("text", "")) for term in margin_terms)
    ]
    need_outline = bool(re.search(r"제\s*\d+장|몇.*장|장.*몇|조문|부칙|신설", query)) or bool(
        removed
    )
    # No unbounded structure payload and no claim that a truncated outline is complete.
    structure = dict(
        doc_id=doc_id,
        path=source["path"],
        transfer_class=source["transfer_class"],
        lists=lists,
        outline=outline[:128] if need_outline else [],
        complete=len(outline) <= 128,
        counts={"장": len(chapters), "조문": len(article_ids)},
        removed=removed,
        source_hash=parsed.source_hash,
    )
    indexer.last_diagnostics.update(
        context_strategy="document-structure" if is_broad else "same-article",
        selected_chunks=len(selected),
    )
    return selected, (structure,)

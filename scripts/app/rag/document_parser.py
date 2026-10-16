"""Local text/PDF extraction with auditable layout cleanup and legal structure.

PDF text is untrusted source data. No model, network, OCR or document instructions
are executed here. Offsets refer to the persisted Markdown, pages to the PDF.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any

PARSER_POLICY = "text-pdf-legal-v1:pdfplumber-0.11.9"
ARTICLE = re.compile(r"^(제\d+조(?:의\d+)?\([^)]*\))\s*(.*)$")
CHAPTER = re.compile(r"^제\d+[편장절관]\s")
PARAGRAPH = re.compile(r"^([①-⑳])")
ITEM = re.compile(r"^(\d+)\.\s+(?!\d)")


class PDFNeedsOCR(ValueError):
    """A page contains images but no extractable text; do not silently omit it."""


@dataclass(frozen=True)
class SourceSpan:
    start: int
    end: int
    page: int
    chapter: str = ""
    article: str = ""
    paragraph: str = ""
    item: str = ""


@dataclass(frozen=True)
class ParsedDocument:
    markdown: str
    source_hash: str
    spans: tuple[SourceSpan, ...] = ()
    removed: tuple[dict[str, Any], ...] = ()
    page_count: int = 0

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_snapshot(cls, value: dict[str, Any]) -> ParsedDocument:
        return cls(
            value["markdown"],
            value["source_hash"],
            tuple(SourceSpan(**s) for s in value.get("spans", [])),
            tuple(value.get("removed", [])),
            value.get("page_count", 0),
        )

    def chunk_metadata(self, start: int, end: int) -> dict[str, Any]:
        spans = [
            s
            for s in self.spans
            if s.start < end
            and s.end > start
            and self.markdown[max(start, s.start) : min(end, s.end)].strip()
        ]
        return {
            "pages": sorted({s.page for s in spans}),
            "structure": list(
                dict.fromkeys(
                    " > ".join(x for x in (s.chapter, s.article, s.paragraph, s.item) if x)
                    for s in spans
                    if s.article or s.chapter
                )
            ),
        }


def _edge(line: dict[str, Any], height: float) -> str:
    if line["bottom"] <= height * 0.08:
        return "header"
    if line["top"] >= height * 0.92:
        return "footer"
    return ""


def _signature(text: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", "", text))


def pdf_to_markdown(pages: list[dict[str, Any]], source_hash: str) -> ParsedDocument:
    """Convert extracted lines; repeated furniture must also be in page margins."""
    occurrences: dict[tuple[str, str], set[int]] = defaultdict(set)
    for page in pages:
        for line in page["lines"]:
            band = _edge(line, page["height"])
            text = line["text"]
            if band and not (ARTICLE.match(text) or CHAPTER.match(text) or PARAGRAPH.match(text)):
                occurrences[(band, _signature(text))].add(page["number"])
    threshold = max(2, math.ceil(len(pages) * 0.6))
    repeated = {key for key, numbers in occurrences.items() if len(numbers) >= threshold}
    output: list[str] = []
    spans: list[SourceSpan] = []
    removed: list[dict[str, Any]] = []
    chapter = article = paragraph = item = ""
    offset = 0
    previous: dict[str, Any] | None = None
    previous_page = 0
    for page in pages:
        for line in page["lines"]:
            text = line["text"].strip()
            if not text:
                continue
            band = _edge(line, page["height"])
            known_footer = band == "footer" and re.fullmatch(
                r"법제처\s+\d+\s+국가법령정보센터", text
            )
            if known_footer or (band, _signature(text)) in repeated:
                removed.append(
                    {
                        "page": page["number"],
                        "text": text,
                        "kind": band,
                        "top": line["top"],
                        "bottom": line["bottom"],
                    }
                )
                continue
            article_match = ARTICLE.match(text)
            paragraph_match = PARAGRAPH.match(text)
            item_match = ITEM.match(text)
            if CHAPTER.match(text) or re.match(r"^부칙(?:\s|$)", text):
                chapter, article, paragraph, item = text, "", "", ""
                rendered = "\n## " + text + "\n\n"
            elif article_match:
                article, paragraph, item = article_match[1], "", ""
                body = article_match[2]
                if first := PARAGRAPH.match(body):
                    paragraph = first[1]
                rendered = "\n### " + article + "\n\n" + (body + "\n" if body else "")
            else:
                if paragraph_match:
                    paragraph, item = paragraph_match[1], ""
                elif item_match:
                    item = item_match[1] + "호"
                # Preserve soft line breaks (never guess Korean word spacing).
                # Legal paragraph/item starts are explicit; generic prose uses
                # vertical gaps only within a page, never a forced page boundary.
                gap = bool(
                    previous
                    and previous_page == page["number"]
                    and line["top"] - previous["bottom"]
                    > max(6, (previous["bottom"] - previous["top"]) * 0.8)
                )
                rendered = (
                    ("\n" if paragraph_match or item_match or (gap and not article) else "")
                    + text
                    + "\n"
                )
            output.append(rendered)
            spans.append(
                SourceSpan(
                    offset,
                    offset + len(rendered),
                    page["number"],
                    chapter,
                    article,
                    paragraph,
                    item,
                )
            )
            offset += len(rendered)
            previous, previous_page = line, page["number"]
    return ParsedDocument("".join(output), source_hash, tuple(spans), tuple(removed), len(pages))


def parse_document(
    raw: bytes, suffix: str, *, max_pages: int = 300, max_characters: int = 2_000_000
) -> ParsedDocument:
    source_hash = hashlib.sha256(raw).hexdigest()
    if suffix.lower() != ".pdf":
        return ParsedDocument(raw.decode("utf-8").replace("\r\n", "\n"), source_hash)
    import pdfplumber

    pages: list[dict[str, Any]] = []
    characters = 0
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        if len(pdf.pages) > max_pages:
            raise ValueError("PDF page limit exceeded")
        for number, page in enumerate(pdf.pages, 1):
            lines = page.extract_text_lines(return_chars=False)
            characters += sum(len(line["text"]) for line in lines)
            if characters > max_characters:
                raise ValueError("PDF extracted text limit exceeded")
            if not lines and page.images:
                raise PDFNeedsOCR("PDF has an image-only page")
            pages.append({"number": number, "height": page.height, "lines": lines})
            page.close()
    parsed = pdf_to_markdown(pages, source_hash)
    if not parsed.markdown.strip():
        raise ValueError("PDF contains no searchable text")
    return parsed

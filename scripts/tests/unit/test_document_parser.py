import re
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app.rag.document_parser import ParsedDocument, PDFNeedsOCR, parse_document, pdf_to_markdown
from tests.helpers.pdf import text_pdf

pytestmark = pytest.mark.phase3


def line(text, top=100):
    return {"text": text, "top": top, "bottom": top + 12}


def test_repeated_margins_removed_but_same_body_text_and_titles_preserved():
    pages = [
        {
            "number": n,
            "height": 842,
            "lines": [
                line("문서 이름", 30),
                line("문서 이름", 150),
                line(f"본문 {n}", 200),
                line(f"법제처 {n} 국가법령정보센터", 800),
            ],
        }
        for n in (1, 2, 3)
    ]
    parsed = pdf_to_markdown(pages, "hash")
    assert len(parsed.removed) == 6
    assert parsed.markdown.count("문서 이름") == 3
    assert "국가법령정보센터" not in parsed.markdown
    assert {s.page for s in parsed.spans} == {1, 2, 3}


def test_unique_margin_text_is_not_deleted_and_article_heading_never_deduplicated():
    pages = [
        {
            "number": n,
            "height": 842,
            "lines": [
                line("제1조(본문) 중요한 본문", 30),
                line(f"서로 다른 주석 {n}번", 400),
            ],
        }
        for n in (1, 2)
    ]
    parsed = pdf_to_markdown(pages, "hash")
    assert not parsed.removed
    assert parsed.markdown.count("중요한 본문") == 2


def test_cross_page_article_paragraph_item_and_appendix_structure():
    pages = [
        {
            "number": 1,
            "height": 842,
            "lines": [
                line("제1장 기본"),
                line("제25조(규정) ① 첫 항의 이어지는", 130),
                line("법제처 1 국가법령정보센터", 800),
            ],
        },
        {
            "number": 2,
            "height": 842,
            "lines": [
                line("내용입니다.", 100),
                line("② 둘째 항입니다.", 120),
                line("1. 첫 호", 140),
                line("2. 둘째 호", 160),
                line("부칙 <제1호>", 200),
                line("제1조(시행일) 부칙 본문", 220),
                line("법제처 2 국가법령정보센터", 800),
            ],
        },
    ]
    parsed = pdf_to_markdown(pages, "hash")
    assert "이어지는\n내용입니다." in parsed.markdown
    assert parsed.spans[2].article == "제25조(규정)"
    assert parsed.spans[2].paragraph == "①"
    assert parsed.spans[4].paragraph == "②" and parsed.spans[4].item == "1호"
    assert parsed.spans[-1].chapter == "부칙 <제1호>"
    assert ParsedDocument.from_snapshot(parsed.snapshot()) == parsed
    metadata = parsed.chunk_metadata(0, len(parsed.markdown))
    assert metadata["pages"] == [1, 2]
    assert any("제25조(규정) > ② > 2호" in s for s in metadata["structure"])
    retained = "".join(
        entry["text"] for p in pages for entry in p["lines"] if "법제처" not in entry["text"]
    )
    assert re.sub(r"\s|#", "", parsed.markdown) == re.sub(r"\s", "", retained)


def test_real_pdf_extracts_pages_and_enforces_limits():
    raw = text_pdf([["Hello PDF", "First page"], ["Second page"]])
    parsed = parse_document(raw, ".PDF")
    assert parsed.page_count == 2 and "Second page" in parsed.markdown
    assert {s.page for s in parsed.spans} == {1, 2}
    with pytest.raises(ValueError, match="page limit"):
        parse_document(raw, ".pdf", max_pages=1)
    with pytest.raises(ValueError, match="text limit"):
        parse_document(raw, ".pdf", max_characters=5)


def test_chunk_metadata_excludes_only_whitespace_from_next_article():
    parsed = pdf_to_markdown(
        [
            {
                "number": 1,
                "height": 800,
                "lines": [
                    {"text": "제1조(목적) 본문이다.", "top": 100, "bottom": 110},
                    {"text": "제2조(정의) 다음 본문이다.", "top": 130, "bottom": 140},
                ],
            }
        ],
        "hash",
    )
    first = parsed.chunk_metadata(0, parsed.markdown.index("### 제2조"))
    assert first["structure"] == ["제1조(목적)"]


def test_image_only_page_fails_explicitly_instead_of_partial_success(monkeypatch):
    import pdfplumber

    page = SimpleNamespace(extract_text_lines=lambda **kw: [], images=[{}])
    monkeypatch.setattr(
        pdfplumber, "open", lambda *args: nullcontext(SimpleNamespace(pages=[page]))
    )
    with pytest.raises(PDFNeedsOCR):
        parse_document(b"fake", ".pdf")


def test_corrupt_or_empty_pdf_rejected_and_utf8_still_supported():
    from pdfplumber.utils.exceptions import PdfminerException

    with pytest.raises(PdfminerException):
        parse_document(b"%PDF broken", ".pdf")
    with pytest.raises(ValueError, match="no searchable text"):
        parse_document(text_pdf([[]]), ".pdf")
    assert parse_document("본문\r\n끝".encode(), ".md").markdown == "본문\n끝"

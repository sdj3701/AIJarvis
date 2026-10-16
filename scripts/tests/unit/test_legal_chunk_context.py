from dataclasses import replace

import pytest

from app.rag.chunker import document_chunks
from app.rag.document_parser import pdf_to_markdown
from tests.unit.test_chunker_indexer import indexer  # noqa: F401

pytestmark = pytest.mark.phase3


def test_four_short_articles_pack_but_fifth_and_new_chapter_do_not():
    text = (
        "## 제1장\n\n"
        + "\n\n".join(f"### 제{i}조(규정)\n\n담당부서는 부서{i}이다." for i in range(1, 6))
        + "\n\n## 제2장\n\n### 제6조(규정)\n\n다른 장의 규정이다."
    )
    chunks = document_chunks(
        text,
        title="test",
        count_tokens=lambda body, title: len(body + title),
        tokenizer_id="test",
        max_tokens=400,
    )
    assert len(chunks) == 3
    assert all(f"제{i}조" in chunks[0].text for i in range(1, 5))
    assert "제5조" not in chunks[0].text and "제6조" not in chunks[1].text
    assert "".join(c.text for c in chunks) == text
    assert all(c.token_count <= 400 for c in chunks)


def test_tail_search_adds_article_premise_without_adjacency(indexer, monkeypatch):  # noqa: F811
    lines = ["제1장 벌칙", "제1조(벌칙) ① 사전경고 후 고의 위반은 5년 이하 징역이다."]
    lines += [
        f"{i}. 표적{i} " + "대상 기록의 승인 날짜를 바꾸어 제출하는 경우이다. " * 3
        for i in range(1, 9)
    ]
    parsed = pdf_to_markdown(
        [
            {
                "number": 1,
                "height": 2000,
                "lines": [
                    {"text": line, "top": 200 + i * 30, "bottom": 212 + i * 30}
                    for i, line in enumerate(lines)
                ],
            }
        ],
        "test",
    )
    from app.rag.generations import parse_document

    monkeypatch.setattr(
        "app.rag.generations.parse_document",
        lambda raw, suffix, **kw: parsed if suffix == ".pdf" else parse_document(raw, suffix, **kw),
    )
    ix = replace(
        indexer,
        semantic=None,
        reranker=None,
        settings=indexer.settings.model_copy(
            update={
                "supported_extensions": [".pdf"],
                "chunk_chars": 180,
                "chunk_overlap_chars": 0,
                "neighbor_chunks": 0,
                "max_chunks_per_answer": 3,
                "semantic": indexer.settings.semantic.model_copy(update={"enabled": False}),
                "rerank": indexer.settings.rerank.model_copy(update={"enabled": False}),
            }
        ),
    )
    (ix.docs_root / "stress.pdf").write_bytes(b"fixture parsed by controlled layout adapter")
    assert not ix.sync().errors
    hits = ix.search("표적8")
    assert hits and "표적8" in hits[0].text and hits[0].ordinal >= 2
    assert any("사전경고" in h.text and "5년" in h.text for h in hits)
    assert all(h.spans and h.pages == (1,) for h in hits)

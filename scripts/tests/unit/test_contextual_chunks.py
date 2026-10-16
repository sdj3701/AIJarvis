from itertools import pairwise

import pytest

from app.rag.chunker import contextual_chunks, document_chunks

pytestmark = pytest.mark.phase3


def count(text, title):
    # Deliberately unlike character count: Korean characters cost more than ASCII.
    return 8 + len(title) + sum(2 if ord(c) > 127 else 1 for c in text)


def test_sections_offsets_and_complete_tail():
    text = (
        "# 출장\n\n식비는 30000원입니다.\n\n"
        + "설명입니다. " * 60
        + "정답 97531\n\n## 숙박\n호텔 규정입니다."
    )
    chunks = contextual_chunks(
        text,
        title="travel.md",
        count_tokens=count,
        tokenizer_id="test-v1",
        max_tokens=128,
        overlap_tokens=12,
        max_chars=300,
        overlap_chars=25,
    )
    assert all(c.token_count <= 128 for c in chunks)
    assert all(c.text == text[c.start_char : c.end_char] for c in chunks)
    assert any("97531" in c.text for c in chunks)
    assert chunks[-1].title.endswith("출장 > 숙박")
    covered = set()
    for c in chunks:
        covered.update(range(c.start_char, c.end_char))
    assert len(covered) == len(text)
    assert all(a.start_char < b.start_char for a, b in pairwise(chunks))


def test_code_headings_are_not_section_titles_and_lexical_fallback_is_explicit():
    text = "# Heading\n```python\n# comment\nprint(1)\n```\n\nend"
    chunks = contextual_chunks(
        text,
        title="code",
        count_tokens=None,
        tokenizer_id="lexical-only",
        max_chars=100,
        overlap_chars=10,
    )
    assert all("comment" not in c.title for c in chunks)
    assert all(c.token_count is None for c in chunks)


def test_unbounded_title_is_rejected_instead_of_truncating_source():
    with pytest.raises(ValueError, match="title"):
        contextual_chunks(
            "body",
            title="x" * 100,
            count_tokens=count,
            tokenizer_id="test",
            max_tokens=64,
            overlap_tokens=8,
        )


def split_document(text, **overrides):
    options = dict(
        title="doc",
        count_tokens=count,
        tokenizer_id="test",
        max_tokens=100,
        overlap_tokens=15,
        max_chars=200,
        overlap_chars=25,
    )
    options.update(overrides)
    return document_chunks(text, **options)


def test_fitting_paragraph_is_not_partly_packed_into_preceding_chunk():
    first = "A" * 40 + ".\n\n"
    second = "B" * 30 + ". " + "C" * 35 + "."
    chunks = split_document(first + second)
    assert [c.text for c in chunks] == [first, second]


def test_short_document_stays_whole_and_large_paragraph_splits_by_sentence():
    short = "짧은 문단입니다.\n\n다음 문단입니다."
    assert [c.text for c in split_document(short)] == [short]
    sentences = [letter * 45 + ". " for letter in "ABC"]
    assert [c.text for c in split_document("".join(sentences))] == sentences


def test_words_stay_whole_until_one_word_itself_exceeds_budget():
    text = " ".join(["한국어어절" * 3] * 8)
    chunks = split_document(text)
    assert all(c.start_char == 0 or text[c.start_char - 1].isspace() for c in chunks)
    assert all(c.end_char == len(text) or text[c.end_char - 1].isspace() for c in chunks)
    unbroken = "한😀글" * 100
    chunks = split_document(unbroken, overlap_tokens=0, overlap_chars=0)
    assert "".join(c.text for c in chunks) == unbroken
    assert all(c.token_count <= 100 for c in chunks)


def test_overlap_preserves_whole_sentences_and_both_limits():
    text = "".join(letter * 18 + ". " for letter in "ABCDEFG")
    chunks = split_document(text, overlap_tokens=25)
    assert chunks[1].start_char == 60
    assert chunks[0].text[-20:] == chunks[1].text[:20]
    for a, b in pairwise(chunks):
        overlap = text[b.start_char : a.end_char]
        assert len(overlap) <= 25
        assert count(overlap, "doc") - count("", "doc") <= 25
        assert a.start_char < b.start_char and a.end_char < b.end_char


@pytest.mark.parametrize(
    "block",
    [
        "```python\n# not a title\nprint('a. b.')\n```\n",
        "| A | B |\n|---|---|\n| a. b. | c |\n",
    ],
)
def test_fitting_code_and_table_blocks_are_not_split_to_fill_previous_chunk(block):
    prefix = "x" * 60 + "\n\n"
    chunks = split_document(prefix + block)
    assert [c.text for c in chunks] == [prefix, block]
    assert all("not a title" not in c.title for c in chunks)


def test_fence_of_different_type_does_not_create_fake_section():
    text = "````text\n~~~\n# not a heading\n```\n````\n# Real\nend"
    chunks = split_document(text)
    assert chunks[-1].title == "doc > Real"
    assert all("not a heading" not in c.title for c in chunks)


@pytest.mark.parametrize("seed", range(10))
def test_mixed_documents_have_no_gaps_and_obey_budgets(seed):
    import random

    rng = random.Random(seed)
    text = "".join(
        rng.choice(["한글 ", "😀", "x.", "\n\n", "abcdef", "\n# 절\n"]) for _ in range(120)
    )
    chunks = split_document(text)
    assert chunks[0].start_char == 0 and chunks[-1].end_char == len(text)
    assert all(c.text == text[c.start_char : c.end_char] for c in chunks)
    assert all(c.token_count <= 100 and len(c.text) <= 200 for c in chunks)
    assert all(a.start_char < b.start_char <= a.end_char < b.end_char for a, b in pairwise(chunks))


def test_empty_document_and_impossibly_small_body_budget():
    assert split_document("") == ()
    with pytest.raises(ValueError, match="source character"):
        split_document("한", max_tokens=12, overlap_tokens=0)


def test_model_context_overflow_during_counting_causes_further_splitting():
    from app.rag.local_embedder import EmbeddingInputTooLong

    def bounded_count(text, title):
        if len(text) > 50:
            raise EmbeddingInputTooLong("too many tokens")
        return count(text, title)

    text = "\U00020000" * 120
    chunks = split_document(text, count_tokens=bounded_count, overlap_chars=0)
    assert "".join(c.text for c in chunks) == text
    assert all(c.token_count == count(c.text, c.title) <= 100 for c in chunks)


def test_counter_outage_is_not_treated_as_a_smaller_chunk_request():
    def unavailable(text, title):
        if text:
            raise OSError("offline")
        return 10

    with pytest.raises(OSError, match="offline"):
        split_document("document", count_tokens=unavailable)


def test_parent_headings_are_attached_to_body_and_never_standalone_hits():
    text = "# Law\n\n## Chapter\n\n### Article\n\nBody.\n\n## Empty end\n"
    chunks = split_document(text, max_tokens=200)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].title.endswith("Law > Chapter > Article")
    assert split_document("# Title\n\n## Empty\n") == ()


def test_revision_date_remains_with_fitting_paragraph():
    first = "첫 번째 문장입니다.\n\n"
    second = "다음 규정입니다. <개정 2008. 2. 29., 2013. 3. 23.>\n"
    chunks = split_document(first + second, max_tokens=90)
    assert any(second in c.text for c in chunks)

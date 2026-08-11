"""Pure ranking helper tests for Phase 2 memory search."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.memory.models import MemoryRecord, MemorySearchResult, ScoredRecord, new_fact_id
from app.memory.retrieval import (
    collapse_same_key,
    extract_key_candidates,
    finalize_search,
    recency_score,
)

pytestmark = pytest.mark.phase2
KST = timezone(timedelta(hours=9), name="KST")
BASE = datetime(2026, 8, 11, 12, 0, tzinfo=KST)
SESSION = "ses_01KZQ6CQWDC6W068WDYMT2ZY4C"
TURN = "turn_01KZQ6CQWDC6W068WDYMT2ZY4C"


def _record(
    *,
    record_id: str,
    key: str,
    value: str,
    kind: str = "fact",
    status: str = "confirmed",
    updated_at: datetime | None = None,
) -> MemoryRecord:
    stamp = updated_at or BASE
    return MemoryRecord(
        id=record_id,
        schema_version=1,
        kind=kind,  # type: ignore[arg-type]
        key=key,
        value=value,
        status=status,  # type: ignore[arg-type]
        source_session_id=SESSION,
        source_turn_id=TURN,
        source_kind="user_explicit",
        created_at=stamp,
        updated_at=stamp,
        expires_at=None,
        sensitivity="normal",
        supersedes=None,
        tags=(),
    )


def _scored(record: MemoryRecord, score: float) -> ScoredRecord:
    return ScoredRecord(record, score, "key_exact")


def test_correction_supersedes_same_key_only() -> None:
    style_old = _record(
        record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4A",
        key="pref.answer_style",
        value="길게",
        updated_at=BASE,
    )
    style_new = _record(
        record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4C",
        key="pref.answer_style",
        kind="correction",
        value="짧게",
        updated_at=BASE + timedelta(hours=1),
    )
    lang_old = _record(
        record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4B",
        key="pref.language",
        value="한국어",
        updated_at=BASE,
    )

    collapsed = collapse_same_key(
        [
            _scored(style_old, 0.9),
            _scored(lang_old, 0.8),
            _scored(style_new, 0.7),
        ]
    )

    by_key = {item.record.key: item.record for item in collapsed}
    assert by_key["pref.answer_style"].kind == "correction"
    assert by_key["pref.answer_style"].value == "짧게"
    assert by_key["pref.language"].value == "한국어"


def test_candidate_not_asserted_as_fact() -> None:
    confirmed = _scored(
        _record(
            record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4A",
            key="pref.answer_style",
            value="짧게",
        ),
        0.9,
    )
    candidate = _scored(
        _record(
            record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4C",
            key="pref.language",
            value="영어",
            status="candidate",
        ),
        0.8,
    )

    result = finalize_search([confirmed], [candidate], top_k=8, min_score=0.0, max_candidates=3)

    assert isinstance(result, MemorySearchResult)
    assert len(result.matches) == 1
    assert result.matches[0].record.status == "confirmed"
    assert len(result.candidates) == 1
    assert result.candidates[0].record.status == "candidate"
    assert result.matches[0].record.id not in {item.record.id for item in result.candidates}


def test_recency_score_half_life() -> None:
    half_lives = {"fact": 180.0}
    fresh = recency_score("fact", 0.0, half_lives)
    aged = recency_score("fact", 180.0, half_lives)
    assert fresh == pytest.approx(1.0)
    assert aged == pytest.approx(0.5)


def test_extract_key_candidates_alias_order() -> None:
    aliases = {
        "pref.answer_style": ["말투", "답변 스타일"],
        "pref.language": ["언어"],
    }
    keys = extract_key_candidates("말투와 언어 설정", aliases)
    assert keys == ("pref.answer_style", "pref.language")


def test_finalize_search_min_score_filters_low_items() -> None:
    high = _scored(
        _record(
            record_id=new_fact_id(),
            key="pref.answer_style",
            value="짧게",
        ),
        0.8,
    )
    low = _scored(
        _record(
            record_id=new_fact_id(),
            key="pref.language",
            value="영어",
        ),
        0.1,
    )

    result = finalize_search([high, low], (), top_k=8, min_score=0.5, max_candidates=0)

    assert len(result.matches) == 1
    assert result.matches[0].record.key == "pref.answer_style"

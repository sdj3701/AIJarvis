# 파이썬 공부 | scripts/tests/unit/test_retrieval_ranking.py
# retrieval_ranking 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase2
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 BASE에 대입합니다.
BASE = datetime(2026, 8, 11, 12, 0, tzinfo=KST)
# SESSION에 문자열을 대입합니다.
SESSION = "ses_01KZQ6CQWDC6W068WDYMT2ZY4C"
# TURN에 문자열을 대입합니다.
TURN = "turn_01KZQ6CQWDC6W068WDYMT2ZY4C"


# _record(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: record_id, key, value, kind, status, updated_at.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: MemoryRecord.
def _record(
    *,
    record_id: str,
    key: str,
    value: str,
    kind: str = "fact",
    status: str = "confirmed",
    updated_at: datetime | None = None,
) -> MemoryRecord:
    # 오른쪽 식을 계산한 값을 stamp에 대입합니다.
    stamp = updated_at or BASE
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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


# _scored(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: record, score.
# 반환 타입 힌트: ScoredRecord.
def _scored(record: MemoryRecord, score: float) -> ScoredRecord:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return ScoredRecord(record, score, "key_exact")


# pytest가 test_correction_supersedes_same_key_only()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_correction_supersedes_same_key_only() -> None:
    # _record()의 반환값을 style_old에 대입합니다.
    style_old = _record(
        record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4A",
        key="pref.answer_style",
        value="길게",
        updated_at=BASE,
    )
    # _record()의 반환값을 style_new에 대입합니다.
    style_new = _record(
        record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4C",
        key="pref.answer_style",
        kind="correction",
        value="짧게",
        updated_at=BASE + timedelta(hours=1),
    )
    # _record()의 반환값을 lang_old에 대입합니다.
    lang_old = _record(
        record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4B",
        key="pref.language",
        value="한국어",
        updated_at=BASE,
    )

    # collapse_same_key()의 반환값을 collapsed에 대입합니다.
    collapsed = collapse_same_key(
        [
            _scored(style_old, 0.9),
            _scored(lang_old, 0.8),
            _scored(style_new, 0.7),
        ]
    )

    # 오른쪽 식을 계산한 값을 by_key에 대입합니다.
    # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
    by_key = {item.record.key: item.record for item in collapsed}
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert by_key["pref.answer_style"].kind == "correction"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert by_key["pref.answer_style"].value == "짧게"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert by_key["pref.language"].value == "한국어"


# pytest가 test_candidate_not_asserted_as_fact()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_candidate_not_asserted_as_fact() -> None:
    # _scored()의 반환값을 confirmed에 대입합니다.
    confirmed = _scored(
        _record(
            record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4A",
            key="pref.answer_style",
            value="짧게",
        ),
        0.9,
    )
    # _scored()의 반환값을 candidate에 대입합니다.
    candidate = _scored(
        _record(
            record_id="fact_01KZQ6CQWDC6W068WDYMT2ZY4C",
            key="pref.language",
            value="영어",
            status="candidate",
        ),
        0.8,
    )

    # finalize_search()의 반환값을 result에 대입합니다.
    result = finalize_search([confirmed], [candidate], top_k=8, min_score=0.0, max_candidates=3)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert isinstance(result, MemorySearchResult)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(result.matches) == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.matches[0].record.status == "confirmed"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(result.candidates) == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.candidates[0].record.status == "candidate"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.matches[0].record.id not in {item.record.id for item in result.candidates}


# pytest가 test_recency_score_half_life()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_recency_score_half_life() -> None:
    # half_lives에 딕셔너리(키와 값의 쌍)을 대입합니다.
    half_lives = {"fact": 180.0}
    # recency_score()의 반환값을 fresh에 대입합니다.
    fresh = recency_score("fact", 0.0, half_lives)
    # recency_score()의 반환값을 aged에 대입합니다.
    aged = recency_score("fact", 180.0, half_lives)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert fresh == pytest.approx(1.0)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert aged == pytest.approx(0.5)


# pytest가 test_extract_key_candidates_alias_order()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_extract_key_candidates_alias_order() -> None:
    # aliases에 딕셔너리(키와 값의 쌍)을 대입합니다.
    aliases = {
        "pref.answer_style": ["말투", "답변 스타일"],
        "pref.language": ["언어"],
    }
    # extract_key_candidates()의 반환값을 keys에 대입합니다.
    keys = extract_key_candidates("말투와 언어 설정", aliases)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert keys == ("pref.answer_style", "pref.language")


# pytest가 test_finalize_search_min_score_filters_low_items()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_finalize_search_min_score_filters_low_items() -> None:
    # _scored()의 반환값을 high에 대입합니다.
    high = _scored(
        _record(
            record_id=new_fact_id(),
            key="pref.answer_style",
            value="짧게",
        ),
        0.8,
    )
    # _scored()의 반환값을 low에 대입합니다.
    low = _scored(
        _record(
            record_id=new_fact_id(),
            key="pref.language",
            value="영어",
        ),
        0.1,
    )

    # finalize_search()의 반환값을 result에 대입합니다.
    result = finalize_search([high, low], (), top_k=8, min_score=0.5, max_candidates=0)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(result.matches) == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.matches[0].record.key == "pref.answer_style"

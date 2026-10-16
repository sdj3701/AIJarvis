# 파이썬 공부 | scripts/app/memory/retrieval.py
# 질문과 관련 있는 기억을 점수화하고 순서를 정합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Pure ranking helpers for Phase 2 memory search (DESIGN chapter 8)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

from app.memory.models import (
    MemoryRecord,
    MemorySearchResult,
    RecordKind,
    ScoredRecord,
)

# re.compile()의 반환값을 _TOKEN_SPLIT에 대입합니다.
_TOKEN_SPLIT = re.compile(r"[\s,./\\|_-]+")


# extract_key_candidates(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text, aliases.
# 반환 타입 힌트: tuple[str, ...].
def extract_key_candidates(
    text: str,
    aliases: Mapping[str, Sequence[str]],
) -> tuple[str, ...]:
    # text.casefold()의 반환값을 normalized에 대입합니다.
    normalized = text.casefold()
    # found에 리스트(순서가 있고 수정 가능)을 대입합니다.
    found: list[str] = []
    # for 반복문: 대상의 항목을 하나씩 (key, words)에 대입하며 아래 블록을 실행합니다.
    for key, words in aliases.items():
        # for 반복문: 대상의 항목을 하나씩 word에 대입하며 아래 블록을 실행합니다.
        for word in words:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: word.casefold() in normalized.
            if word.casefold() in normalized:
                # 리스트 끝에 항목 하나를 추가합니다.
                found.append(key)
                # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                break
    # Preserve first-seen order without duplicates.
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return tuple(dict.fromkeys(found))


# recency_score(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: kind, age_days, half_life_days.
# 반환 타입 힌트: 실수(float).
def recency_score(kind: RecordKind, age_days: float, half_life_days: Mapping[str, float]) -> float:
    # float()의 반환값을 half_life에 대입합니다.
    half_life = float(half_life_days.get(kind, 180))
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: half_life <= 0.
    if half_life <= 0:
        # 0.0을 반환하고 이 함수의 실행을 끝냅니다.
        return 0.0
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return float(0.5 ** (max(0.0, age_days) / half_life))


# age_days(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: updated_at, now.
# 반환 타입 힌트: 실수(float).
def age_days(updated_at: datetime, now: datetime) -> float:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return max(0.0, (now - updated_at).total_seconds() / 86_400.0)


# normalize_bm25(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: raw, floor, ceiling.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 실수(float).
def normalize_bm25(raw: float, *, floor: float = -20.0, ceiling: float = 20.0) -> float:
    # min()의 반환값을 clipped에 대입합니다.
    clipped = min(ceiling, max(floor, raw))
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return (clipped - floor) / (ceiling - floor)


# score_record(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: record, relevance, matched_on, now, kind_weights, half_life_days.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: ScoredRecord.
def score_record(
    record: MemoryRecord,
    *,
    relevance: float,
    matched_on: str,
    now: datetime,
    kind_weights: Mapping[str, float],
    half_life_days: Mapping[str, float],
) -> ScoredRecord:
    # float()의 반환값을 weight에 대입합니다.
    weight = float(kind_weights.get(record.kind, 0.5))
    # 오른쪽 식을 계산한 값을 score에 대입합니다.
    score = weight * relevance * recency_score(
        record.kind, age_days(record.updated_at, now), half_life_days
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return ScoredRecord(record, score, matched_on)  # type: ignore[arg-type]


# collapse_same_key(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: scored.
# 반환 타입 힌트: list[ScoredRecord].
def collapse_same_key(scored: Sequence[ScoredRecord]) -> list[ScoredRecord]:
    """Keep the newest confirmed record per key; corrections win only inside that key."""
    # by_key에 딕셔너리(키와 값의 쌍)을 대입합니다.
    by_key: dict[str, ScoredRecord] = {}
    # leftover에 리스트(순서가 있고 수정 가능)을 대입합니다.
    leftover: list[ScoredRecord] = []
    # for 반복문: 대상의 항목을 하나씩 item에 대입하며 아래 블록을 실행합니다.
    for item in scored:
        # 오른쪽 식을 계산한 값을 key에 대입합니다.
        key = item.record.key
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: key is None.
        if key is None:
            # 리스트 끝에 항목 하나를 추가합니다.
            leftover.append(item)
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # by_key.get()의 반환값을 current에 대입합니다.
        current = by_key.get(key)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: current is None.
        if current is None:
            # 오른쪽 식을 계산한 값을 by_key[key]에 대입합니다.
            by_key[key] = item
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # Prefer correction over fact when timestamps equal; otherwise newest updated_at.
        # 오른쪽 식을 계산한 값을 is_newer에 대입합니다.
        is_newer = item.record.updated_at > current.record.updated_at
        # 오른쪽 식을 계산한 값을 same_time_preferred에 대입합니다.
        same_time_preferred = item.record.updated_at == current.record.updated_at and (
            (item.record.kind == "correction" and current.record.kind != "correction")
            or item.record.id > current.record.id
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: is_newer or same_time_preferred.
        if is_newer or same_time_preferred:
            # 오른쪽 식을 계산한 값을 by_key[key]에 대입합니다.
            by_key[key] = item
    # 오른쪽 식을 계산한 값을 merged에 대입합니다.
    merged = list(by_key.values()) + leftover
    # merged.sort()을 호출해 작업을 수행합니다.
    merged.sort(key=lambda item: (-item.score, item.record.id), reverse=False)
    # score desc, id desc for ties
    # merged.sort()을 호출해 작업을 수행합니다.
    merged.sort(key=lambda item: (item.score, item.record.id), reverse=True)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return merged


# finalize_search(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: confirmed, candidates, top_k, min_score, max_candidates.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: MemorySearchResult.
def finalize_search(
    confirmed: Sequence[ScoredRecord],
    candidates: Sequence[ScoredRecord],
    *,
    top_k: int,
    min_score: float,
    max_candidates: int,
) -> MemorySearchResult:
    # 오른쪽 식을 계산한 값을 confirmed_kept에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    confirmed_kept = [item for item in collapse_same_key(confirmed) if item.score >= min_score]
    # 오른쪽 식을 계산한 값을 confirmed_kept에 대입합니다.
    # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
    confirmed_kept = confirmed_kept[: max(0, top_k)]
    # 오른쪽 식을 계산한 값을 candidate_kept에 대입합니다.
    # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
    candidate_kept = [
        item for item in collapse_same_key(candidates) if item.score >= min_score
    ][: max(0, max_candidates)]
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return MemorySearchResult(tuple(confirmed_kept), tuple(candidate_kept))


# fts_match_query(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text.
# 반환 타입 힌트: 문자열(str).
def fts_match_query(text: str) -> str:
    """Build a conservative FTS5 MATCH string from free text."""
    # 오른쪽 식을 계산한 값을 tokens에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    tokens = [token for token in _TOKEN_SPLIT.split(text.strip()) if len(token) >= 2]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not tokens.
    if not tokens:
        # re.sub()의 반환값을 cleaned에 대입합니다.
        cleaned = re.sub(r"\s+", "", text.strip())
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        return cleaned[:32] if cleaned else text.strip()[:32]
    # Quote tokens to reduce syntax errors; trigram still matches substrings.
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens[:12])


# cosine_placeholder(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: _left, _right.
# 반환 타입 힌트: 실수(float).
def cosine_placeholder(_left: object, _right: object) -> float:
    """Embeddings stay disabled in Phase 2."""
    # 0.0을 반환하고 이 함수의 실행을 끝냅니다.
    return 0.0


# combine_relevance(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: bm25_norm, cosine, fts_weight, embedding_weight.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 실수(float).
def combine_relevance(
    *,
    bm25_norm: float | None,
    cosine: float | None,
    fts_weight: float,
    embedding_weight: float,
) -> float:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: bm25_norm is None and cosine is None.
    if bm25_norm is None and cosine is None:
        # 0.0을 반환하고 이 함수의 실행을 끝냅니다.
        return 0.0
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: bm25_norm is not None and cosine is not
    # None.
    if bm25_norm is not None and cosine is not None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return fts_weight * bm25_norm + embedding_weight * cosine
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: bm25_norm is not None.
    if bm25_norm is not None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return bm25_norm
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return float(cosine or 0.0)


# stable_tiebreak_key(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: item.
# 반환 타입 힌트: tuple[float, str].
def stable_tiebreak_key(item: ScoredRecord) -> tuple[float, str]:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return (item.score, item.record.id)


# format_confirmed_memory_block(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: items, omitted.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 문자열(str).
def format_confirmed_memory_block(
    items: Sequence[ScoredRecord],
    *,
    omitted: int = 0,
) -> str:
    # lines에 리스트(순서가 있고 수정 가능)을 대입합니다.
    lines = ["<confirmed_memory>"]
    # for 반복문: 대상의 항목을 하나씩 item에 대입하며 아래 블록을 실행합니다.
    for item in items:
        # 오른쪽 식을 계산한 값을 key에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        key = f"[{item.record.key}] " if item.record.key else ""
        # 리스트 끝에 항목 하나를 추가합니다.
        lines.append(f"- {key}{item.record.value}")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: omitted > 0.
    if omitted > 0:
        # 리스트 끝에 항목 하나를 추가합니다.
        lines.append(f"(관련 기억 {omitted}건 생략)")
    # 리스트 끝에 항목 하나를 추가합니다.
    lines.append("</confirmed_memory>")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return "\n".join(lines)


# format_candidate_memory_block(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: items, omitted.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 문자열(str).
def format_candidate_memory_block(
    items: Sequence[ScoredRecord],
    *,
    omitted: int = 0,
) -> str:
    # lines에 리스트(순서가 있고 수정 가능)을 대입합니다.
    lines = [
        "<candidate_memory>",
        "아래는 아직 확인되지 않은 추정입니다. "
        "사실로 단정하지 말고 필요하면 사용자에게 확인하세요.",
    ]
    # for 반복문: 대상의 항목을 하나씩 item에 대입하며 아래 블록을 실행합니다.
    for item in items:
        # 오른쪽 식을 계산한 값을 key에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        key = f"[{item.record.key}] " if item.record.key else ""
        # 리스트 끝에 항목 하나를 추가합니다.
        lines.append(f"- {key}{item.record.value}")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: omitted > 0.
    if omitted > 0:
        # 리스트 끝에 항목 하나를 추가합니다.
        lines.append(f"(미확정 기억 {omitted}건 생략)")
    # 리스트 끝에 항목 하나를 추가합니다.
    lines.append("</candidate_memory>")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return "\n".join(lines)


# trim_memory_for_budget(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: confirmed, candidates, token_budget, count_tokens.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: tuple[tuple[ScoredRecord, ...], tuple[ScoredRecord, ...], str | None, str |
# None].
def trim_memory_for_budget(
    confirmed: Sequence[ScoredRecord],
    candidates: Sequence[ScoredRecord],
    *,
    token_budget: int,
    count_tokens: Callable[[str], int],
) -> tuple[tuple[ScoredRecord, ...], tuple[ScoredRecord, ...], str | None, str | None]:
    """Drop lowest-score items until formatted blocks fit token_budget."""
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: token_budget <= 0.
    if token_budget <= 0:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return (), (), None, None

    # list()의 반환값을 confirmed_list에 대입합니다.
    confirmed_list = list(confirmed)
    # list()의 반환값을 candidate_list에 대입합니다.
    candidate_list = list(candidates)
    # dropped_confirmed에 숫자 등 고정된 값을 대입합니다.
    dropped_confirmed = 0
    # dropped_candidates에 숫자 등 고정된 값을 대입합니다.
    dropped_candidates = 0

    # fits(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 반환 타입 힌트: 참/거짓(bool).
    def fits() -> bool:
        # format_confirmed_memory_block()의 반환값을 confirmed_block에 대입합니다.
        confirmed_block = format_confirmed_memory_block(confirmed_list, omitted=dropped_confirmed)
        # 오른쪽 식을 계산한 값을 candidate_block에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        candidate_block = (
            format_candidate_memory_block(candidate_list, omitted=dropped_candidates)
            if candidate_list or dropped_candidates
            else None
        )
        # count_tokens()의 반환값을 total에 대입합니다.
        total = count_tokens(confirmed_block)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: candidate_block is not None.
        if candidate_block is not None:
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            total += count_tokens(candidate_block)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return total <= token_budget

    # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
    while not fits():
        # min()의 반환값을 lowest_confirmed에 대입합니다.
        lowest_confirmed = min(
            confirmed_list,
            key=lambda item: (item.score, item.record.id),
            default=None,
        )
        # min()의 반환값을 lowest_candidate에 대입합니다.
        lowest_candidate = min(
            candidate_list,
            key=lambda item: (item.score, item.record.id),
            default=None,
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: lowest_confirmed is None and
        # lowest_candidate is None.
        if lowest_confirmed is None and lowest_candidate is None:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: dropped_confirmed or
            # dropped_candidates.
            if dropped_confirmed or dropped_candidates:
                # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                break
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return (), (), None, None
        # drop_confirmed을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        drop_confirmed = False
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: lowest_confirmed is not None and
        # lowest_candidate is not
        # None.
        if lowest_confirmed is not None and lowest_candidate is not None:
            # 오른쪽 식을 계산한 값을 drop_confirmed에 대입합니다.
            drop_confirmed = lowest_confirmed.score <= lowest_candidate.score
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: lowest_confirmed is not None.
        elif lowest_confirmed is not None:
            # drop_confirmed을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
            drop_confirmed = True

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: drop_confirmed and lowest_confirmed is
        # not None.
        if drop_confirmed and lowest_confirmed is not None:
            # confirmed_list.remove()을 호출해 작업을 수행합니다.
            confirmed_list.remove(lowest_confirmed)
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            dropped_confirmed += 1
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: lowest_candidate is not None.
        elif lowest_candidate is not None:
            # candidate_list.remove()을 호출해 작업을 수행합니다.
            candidate_list.remove(lowest_candidate)
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            dropped_candidates += 1
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
            break

    # 오른쪽 식을 계산한 값을 confirmed_block에 대입합니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    confirmed_block = (
        format_confirmed_memory_block(confirmed_list, omitted=dropped_confirmed)
        if confirmed_list or dropped_confirmed
        else None
    )
    # 오른쪽 식을 계산한 값을 candidate_block에 대입합니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    candidate_block = (
        format_candidate_memory_block(candidate_list, omitted=dropped_candidates)
        if candidate_list or dropped_candidates
        else None
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return tuple(confirmed_list), tuple(candidate_list), confirmed_block, candidate_block

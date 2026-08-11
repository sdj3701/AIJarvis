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

_TOKEN_SPLIT = re.compile(r"[\s,./\\|_-]+")


def extract_key_candidates(
    text: str,
    aliases: Mapping[str, Sequence[str]],
) -> tuple[str, ...]:
    normalized = text.casefold()
    found: list[str] = []
    for key, words in aliases.items():
        for word in words:
            if word.casefold() in normalized:
                found.append(key)
                break
    # Preserve first-seen order without duplicates.
    return tuple(dict.fromkeys(found))


def recency_score(kind: RecordKind, age_days: float, half_life_days: Mapping[str, float]) -> float:
    half_life = float(half_life_days.get(kind, 180))
    if half_life <= 0:
        return 0.0
    return float(0.5 ** (max(0.0, age_days) / half_life))


def age_days(updated_at: datetime, now: datetime) -> float:
    return max(0.0, (now - updated_at).total_seconds() / 86_400.0)


def normalize_bm25(raw: float, *, floor: float = -20.0, ceiling: float = 20.0) -> float:
    clipped = min(ceiling, max(floor, raw))
    return (clipped - floor) / (ceiling - floor)


def score_record(
    record: MemoryRecord,
    *,
    relevance: float,
    matched_on: str,
    now: datetime,
    kind_weights: Mapping[str, float],
    half_life_days: Mapping[str, float],
) -> ScoredRecord:
    weight = float(kind_weights.get(record.kind, 0.5))
    score = weight * relevance * recency_score(
        record.kind, age_days(record.updated_at, now), half_life_days
    )
    return ScoredRecord(record, score, matched_on)  # type: ignore[arg-type]


def collapse_same_key(scored: Sequence[ScoredRecord]) -> list[ScoredRecord]:
    """Keep the newest confirmed record per key; corrections win only inside that key."""
    by_key: dict[str, ScoredRecord] = {}
    leftover: list[ScoredRecord] = []
    for item in scored:
        key = item.record.key
        if key is None:
            leftover.append(item)
            continue
        current = by_key.get(key)
        if current is None:
            by_key[key] = item
            continue
        # Prefer correction over fact when timestamps equal; otherwise newest updated_at.
        is_newer = item.record.updated_at > current.record.updated_at
        same_time_preferred = item.record.updated_at == current.record.updated_at and (
            (item.record.kind == "correction" and current.record.kind != "correction")
            or item.record.id > current.record.id
        )
        if is_newer or same_time_preferred:
            by_key[key] = item
    merged = list(by_key.values()) + leftover
    merged.sort(key=lambda item: (-item.score, item.record.id), reverse=False)
    # score desc, id desc for ties
    merged.sort(key=lambda item: (item.score, item.record.id), reverse=True)
    return merged


def finalize_search(
    confirmed: Sequence[ScoredRecord],
    candidates: Sequence[ScoredRecord],
    *,
    top_k: int,
    min_score: float,
    max_candidates: int,
) -> MemorySearchResult:
    confirmed_kept = [item for item in collapse_same_key(confirmed) if item.score >= min_score]
    confirmed_kept = confirmed_kept[: max(0, top_k)]
    candidate_kept = [
        item for item in collapse_same_key(candidates) if item.score >= min_score
    ][: max(0, max_candidates)]
    return MemorySearchResult(tuple(confirmed_kept), tuple(candidate_kept))


def fts_match_query(text: str) -> str:
    """Build a conservative FTS5 MATCH string from free text."""
    tokens = [token for token in _TOKEN_SPLIT.split(text.strip()) if len(token) >= 2]
    if not tokens:
        cleaned = re.sub(r"\s+", "", text.strip())
        return cleaned[:32] if cleaned else text.strip()[:32]
    # Quote tokens to reduce syntax errors; trigram still matches substrings.
    return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens[:12])


def cosine_placeholder(_left: object, _right: object) -> float:
    """Embeddings stay disabled in Phase 2."""
    return 0.0


def combine_relevance(
    *,
    bm25_norm: float | None,
    cosine: float | None,
    fts_weight: float,
    embedding_weight: float,
) -> float:
    if bm25_norm is None and cosine is None:
        return 0.0
    if bm25_norm is not None and cosine is not None:
        return fts_weight * bm25_norm + embedding_weight * cosine
    if bm25_norm is not None:
        return bm25_norm
    return float(cosine or 0.0)


def stable_tiebreak_key(item: ScoredRecord) -> tuple[float, str]:
    return (item.score, item.record.id)


def format_confirmed_memory_block(
    items: Sequence[ScoredRecord],
    *,
    omitted: int = 0,
) -> str:
    lines = ["<confirmed_memory>"]
    for item in items:
        key = f"[{item.record.key}] " if item.record.key else ""
        lines.append(f"- {key}{item.record.value}")
    if omitted > 0:
        lines.append(f"(관련 기억 {omitted}건 생략)")
    lines.append("</confirmed_memory>")
    return "\n".join(lines)


def format_candidate_memory_block(
    items: Sequence[ScoredRecord],
    *,
    omitted: int = 0,
) -> str:
    lines = [
        "<candidate_memory>",
        "아래는 아직 확인되지 않은 추정입니다. "
        "사실로 단정하지 말고 필요하면 사용자에게 확인하세요.",
    ]
    for item in items:
        key = f"[{item.record.key}] " if item.record.key else ""
        lines.append(f"- {key}{item.record.value}")
    if omitted > 0:
        lines.append(f"(미확정 기억 {omitted}건 생략)")
    lines.append("</candidate_memory>")
    return "\n".join(lines)


def trim_memory_for_budget(
    confirmed: Sequence[ScoredRecord],
    candidates: Sequence[ScoredRecord],
    *,
    token_budget: int,
    count_tokens: Callable[[str], int],
) -> tuple[tuple[ScoredRecord, ...], tuple[ScoredRecord, ...], str | None, str | None]:
    """Drop lowest-score items until formatted blocks fit token_budget."""
    if token_budget <= 0:
        return (), (), None, None

    confirmed_list = list(confirmed)
    candidate_list = list(candidates)
    dropped_confirmed = 0
    dropped_candidates = 0

    def fits() -> bool:
        confirmed_block = format_confirmed_memory_block(confirmed_list, omitted=dropped_confirmed)
        candidate_block = (
            format_candidate_memory_block(candidate_list, omitted=dropped_candidates)
            if candidate_list or dropped_candidates
            else None
        )
        total = count_tokens(confirmed_block)
        if candidate_block is not None:
            total += count_tokens(candidate_block)
        return total <= token_budget

    while not fits():
        lowest_confirmed = min(
            confirmed_list,
            key=lambda item: (item.score, item.record.id),
            default=None,
        )
        lowest_candidate = min(
            candidate_list,
            key=lambda item: (item.score, item.record.id),
            default=None,
        )
        if lowest_confirmed is None and lowest_candidate is None:
            if dropped_confirmed or dropped_candidates:
                break
            return (), (), None, None
        drop_confirmed = False
        if lowest_confirmed is not None and lowest_candidate is not None:
            drop_confirmed = lowest_confirmed.score <= lowest_candidate.score
        elif lowest_confirmed is not None:
            drop_confirmed = True

        if drop_confirmed and lowest_confirmed is not None:
            confirmed_list.remove(lowest_confirmed)
            dropped_confirmed += 1
        elif lowest_candidate is not None:
            candidate_list.remove(lowest_candidate)
            dropped_candidates += 1
        else:
            break

    confirmed_block = (
        format_confirmed_memory_block(confirmed_list, omitted=dropped_confirmed)
        if confirmed_list or dropped_confirmed
        else None
    )
    candidate_block = (
        format_candidate_memory_block(candidate_list, omitted=dropped_candidates)
        if candidate_list or dropped_candidates
        else None
    )
    return tuple(confirmed_list), tuple(candidate_list), confirmed_block, candidate_block

# 파이썬 공부 | scripts/app/rag/benchmark/metrics.py
# 검색 결과의 품질과 응답 시간 지표를 계산합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Quality and latency metrics for document-level retrieval evaluation."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from statistics import fmean

from app.rag.benchmark.models import RetrievalResult

# QUALITY_CUTOFFS에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
QUALITY_CUTOFFS = (1, 3, 5, 10)
# QUALITY_METRIC_COLUMNS에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
QUALITY_METRIC_COLUMNS = (
    "recall_at_1",
    "recall_at_3",
    "recall_at_5",
    "recall_at_10",
    "mrr_at_5",
    "mrr_at_10",
    "ndcg_at_5",
    "ndcg_at_10",
)


# quality_metrics(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: results, relevant_document_ids.
# 반환 타입 힌트: dict[str, float].
def quality_metrics(
    results: Sequence[RetrievalResult], relevant_document_ids: Iterable[str]
) -> dict[str, float]:
    """Calculate document-level Recall, MRR, and binary nDCG.

    A document may consist of many chunks.  The first returned chunk determines
    its rank and later chunks of the same document do not inflate the score.
    """

    # frozenset()의 반환값을 relevant에 대입합니다.
    relevant = frozenset(relevant_document_ids)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not relevant.
    if not relevant:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("relevant_document_ids가 비어 있으면 품질 지표를 계산할 수 없습니다.")
    # _unique_document_ranking()의 반환값을 ranked_documents에 대입합니다.
    ranked_documents = _unique_document_ranking(results)
    # metrics에 딕셔너리(키와 값의 쌍)을 대입합니다.
    metrics: dict[str, float] = {}
    # for 반복문: 대상의 항목을 하나씩 cutoff에 대입하며 아래 블록을 실행합니다.
    for cutoff in QUALITY_CUTOFFS:
        # _recall_at()의 반환값을 metrics[f'recall_at_{cutoff}']에 대입합니다.
        metrics[f"recall_at_{cutoff}"] = _recall_at(ranked_documents, relevant, cutoff)
    # for 반복문: 대상의 항목을 하나씩 cutoff에 대입하며 아래 블록을 실행합니다.
    for cutoff in (5, 10):
        # _mrr_at()의 반환값을 metrics[f'mrr_at_{cutoff}']에 대입합니다.
        metrics[f"mrr_at_{cutoff}"] = _mrr_at(ranked_documents, relevant, cutoff)
        # _ndcg_at()의 반환값을 metrics[f'ndcg_at_{cutoff}']에 대입합니다.
        metrics[f"ndcg_at_{cutoff}"] = _ndcg_at(ranked_documents, relevant, cutoff)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return metrics


# percentile(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: values, percent.
# 반환 타입 힌트: 실수(float).
def percentile(values: Sequence[float], percent: float) -> float:
    """Return a deterministic linearly interpolated percentile."""

    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not values.
    if not values:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("percentile은 비어 있는 목록에 적용할 수 없습니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not 0 <= percent <= 100.
    if not 0 <= percent <= 100:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("percent는 0과 100 사이여야 합니다.")
    # sorted()의 반환값을 ordered에 대입합니다.
    ordered = sorted(values)
    # 오른쪽 식을 계산한 값을 index에 대입합니다.
    index = (len(ordered) - 1) * (percent / 100)
    # math.floor()의 반환값을 lower에 대입합니다.
    lower = math.floor(index)
    # math.ceil()의 반환값을 upper에 대입합니다.
    upper = math.ceil(index)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: lower == upper.
    if lower == upper:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ordered[lower]
    # 오른쪽 식을 계산한 값을 lower_weight에 대입합니다.
    lower_weight = upper - index
    # 오른쪽 식을 계산한 값을 upper_weight에 대입합니다.
    upper_weight = index - lower
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return ordered[lower] * lower_weight + ordered[upper] * upper_weight


# latency_metrics(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: latencies_ms.
# 반환 타입 힌트: dict[str, float].
def latency_metrics(latencies_ms: Sequence[float]) -> dict[str, float]:
    """Summarize sequential-query latency and its equivalent single-worker QPS."""

    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not latencies_ms.
    if not latencies_ms:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("latency목록이 비어 있습니다.")
    # sum()의 반환값을 total_ms에 대입합니다.
    total_ms = sum(latencies_ms)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return {
        "latency_avg_ms": fmean(latencies_ms),
        "latency_p50_ms": percentile(latencies_ms, 50),
        "latency_p95_ms": percentile(latencies_ms, 95),
        "latency_min_ms": min(latencies_ms),
        "latency_max_ms": max(latencies_ms),
        "qps": len(latencies_ms) / (total_ms / 1000) if total_ms > 0 else 0.0,
    }


# mean_metrics(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: metric_rows.
# 반환 타입 힌트: dict[str, float].
def mean_metrics(metric_rows: Sequence[dict[str, float]]) -> dict[str, float]:
    """Macro-average a non-empty set of query-level metric dictionaries."""

    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not metric_rows.
    if not metric_rows:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("metric_rows걷4 비어 있습니다.")
    # metric_rows[0].keys()의 반환값을 keys에 대입합니다.
    keys = metric_rows[0].keys()
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
    return {key: fmean(row[key] for row in metric_rows) for key in keys}


# _unique_document_ranking(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: results.
# 반환 타입 힌트: list[str].
def _unique_document_ranking(results: Sequence[RetrievalResult]) -> list[str]:
    # set()의 반환값을 seen에 대입합니다.
    seen: set[str] = set()
    # ranked에 리스트(순서가 있고 수정 가능)을 대입합니다.
    ranked: list[str] = []
    # for 반복문: 대상의 항목을 하나씩 result에 대입하며 아래 블록을 실행합니다.
    for result in sorted(results, key=lambda item: item["rank"]):
        # 오른쪽 식을 계산한 값을 document_id에 대입합니다.
        document_id = result["document_id"]
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: document_id not in seen.
        if document_id not in seen:
            # 리스트 끝에 항목 하나를 추가합니다.
            ranked.append(document_id)
            # add 메서드를 호출해 항목이나 기록을 추가합니다.
            seen.add(document_id)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return ranked


# _recall_at(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: ranked, relevant, cutoff.
# 반환 타입 힌트: 실수(float).
def _recall_at(ranked: Sequence[str], relevant: frozenset[str], cutoff: int) -> float:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return len(set(ranked[:cutoff]) & relevant) / len(relevant)


# _mrr_at(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: ranked, relevant, cutoff.
# 반환 타입 힌트: 실수(float).
def _mrr_at(ranked: Sequence[str], relevant: frozenset[str], cutoff: int) -> float:
    # for 반복문: 대상의 항목을 하나씩 (rank, document_id)에 대입하며 아래 블록을 실행합니다.
    for rank, document_id in enumerate(ranked[:cutoff], start=1):
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: document_id in relevant.
        if document_id in relevant:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return 1.0 / rank
    # 0.0을 반환하고 이 함수의 실행을 끝냅니다.
    return 0.0


# _ndcg_at(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: ranked, relevant, cutoff.
# 반환 타입 힌트: 실수(float).
def _ndcg_at(ranked: Sequence[str], relevant: frozenset[str], cutoff: int) -> float:
    # sum()의 반환값을 dcg에 대입합니다.
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, document_id in enumerate(ranked[:cutoff], start=1)
        if document_id in relevant
    )
    # min()의 반환값을 ideal_count에 대입합니다.
    ideal_count = min(len(relevant), cutoff)
    # sum()의 반환값을 ideal_dcg에 대입합니다.
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    return dcg / ideal_dcg if ideal_dcg else 0.0

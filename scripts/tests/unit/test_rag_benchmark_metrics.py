# 파이썬 공부 | scripts/tests/unit/test_rag_benchmark_metrics.py
# rag_benchmark_metrics 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Unit tests for document-level benchmark quality calculations."""

from __future__ import annotations

import pytest

from app.rag.benchmark.metrics import latency_metrics, percentile, quality_metrics


# pytest가 test_quality_metrics_deduplicates_chunks_from_one_document()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_quality_metrics_deduplicates_chunks_from_one_document() -> None:
    # results에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    results = (
        {
            "document_id": "doc_a",
            "chunk_id": "chunk_a1",
            "content": "first",
            "score": 0.9,
            "rank": 1,
        },
        {
            "document_id": "doc_a",
            "chunk_id": "chunk_a2",
            "content": "duplicate document",
            "score": 0.8,
            "rank": 2,
        },
        {
            "document_id": "doc_b",
            "chunk_id": "chunk_b1",
            "content": "second relevant document",
            "score": 0.7,
            "rank": 3,
        },
    )

    # quality_metrics()의 반환값을 metrics에 대입합니다.
    metrics = quality_metrics(results, ("doc_a", "doc_b"))

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert metrics["recall_at_1"] == 0.5
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert metrics["recall_at_3"] == 1.0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert metrics["mrr_at_5"] == 1.0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert metrics["ndcg_at_5"] == pytest.approx(1.0)


# pytest가 test_latency_metrics_and_percentile_are_deterministic()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_latency_metrics_and_percentile_are_deterministic() -> None:
    # values에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    values = (10.0, 20.0, 30.0, 40.0, 50.0)

    # latency_metrics()의 반환값을 summary에 대입합니다.
    summary = latency_metrics(values)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert percentile(values, 95) == 48.0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert summary["latency_avg_ms"] == 30.0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert summary["latency_p50_ms"] == 30.0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert summary["latency_p95_ms"] == 48.0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert summary["qps"] == pytest.approx(1000 / 30)

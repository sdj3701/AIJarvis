# 파이썬 공부 | scripts/app/rag/benchmark/runner.py
# 검색 평가를 반복 실행하고 결과 보고서를 저장합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Orchestrate repeatable retrieval evaluation and write report artifacts."""

from __future__ import annotations

import csv
import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from app.rag.benchmark.metrics import (
    latency_metrics,
    mean_metrics,
    percentile,
    quality_metrics,
)
from app.rag.benchmark.models import EvaluationQuery, IndexedChunk, SearchTrace
from app.rag.benchmark.retrievers import (
    FTS5_NAME,
    RRF_NAME,
    VECTOR_NAME,
    BenchmarkRetriever,
    FTS5SearchRetriever,
    HybridRRFSearchRetriever,
    VectorSearchRetriever,
    load_indexed_chunks,
)
from app.rag.benchmark.visualization import create_benchmark_charts

# DEFAULT_SEED에 숫자 등 고정된 값을 대입합니다.
DEFAULT_SEED = 42


# BenchmarkRunResult: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class BenchmarkRunResult:
    # summary_path: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    summary_path: Path
    # per_query_path: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    per_query_path: Path
    # by_query_type_path: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    by_query_type_path: Path
    # report_path: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    report_path: Path
    # chart_paths: tuple[Path, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    chart_paths: tuple[Path, ...]
    # catalog_path: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    catalog_path: Path
    # summary_rows: tuple[dict[str, Any], ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    summary_rows: tuple[dict[str, Any], ...]
    # query_type_rows: tuple[dict[str, Any], ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    query_type_rows: tuple[dict[str, Any], ...]


# _QueryRun: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class _QueryRun:
    # retriever: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    retriever: str
    # top_k: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    top_k: int
    # query: EvaluationQuery 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    query: EvaluationQuery
    # traces: tuple[SearchTrace, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    traces: tuple[SearchTrace, ...]
    # quality: dict[str, float] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    quality: dict[str, float]


# BenchmarkRunner: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class BenchmarkRunner:
    """Benchmark all three local retrieval strategies against one JSON dataset."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: database_path, evaluation_queries, output_dir, rrf_k, top_k_values, repeats,
    # warmup_queries, seed.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        *,
        database_path: Path,
        evaluation_queries: Sequence[EvaluationQuery],
        output_dir: Path,
        rrf_k: int = 60,
        top_k_values: Sequence[int] = (1, 3, 5, 10),
        repeats: int = 5,
        warmup_queries: int = 10,
        seed: int = DEFAULT_SEED,
    ) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not evaluation_queries.
        if not evaluation_queries:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("평가할 쿼리가 없습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: repeats <= 0.
        if repeats <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("repeats는 0보다 크게 설정해야 합니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: warmup_queries < 0.
        if warmup_queries < 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("warmup_queries는 0 이상이어야 합니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: rrf_k <= 0.
        if rrf_k <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("rrf_k는 0보다 크게 설정해야 합니다.")
        # tuple()의 반환값을 normalized_top_k에 대입합니다.
        normalized_top_k = tuple(dict.fromkeys(top_k_values))
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not normalized_top_k or any(value <= 0 for value in normalized_top_k):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("top_k_values는 하나 이상의 양수여야 합니다.")
        # 오른쪽 식을 계산한 값을 self._database_path에 대입합니다.
        self._database_path = database_path
        # tuple()의 반환값을 self._queries에 대입합니다.
        self._queries = tuple(evaluation_queries)
        # 오른쪽 식을 계산한 값을 self._output_dir에 대입합니다.
        self._output_dir = output_dir
        # 오른쪽 식을 계산한 값을 self._rrf_k에 대입합니다.
        self._rrf_k = rrf_k
        # 오른쪽 식을 계산한 값을 self._top_k_values에 대입합니다.
        self._top_k_values = normalized_top_k
        # 오른쪽 식을 계산한 값을 self._repeats에 대입합니다.
        self._repeats = repeats
        # 오른쪽 식을 계산한 값을 self._warmup_queries에 대입합니다.
        self._warmup_queries = warmup_queries
        # 오른쪽 식을 계산한 값을 self._seed에 대입합니다.
        self._seed = seed

    # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: BenchmarkRunResult.
    def run(self) -> BenchmarkRunResult:
        """Build isolated benchmark indexes, measure searches, and write all outputs."""

        # random.seed()을 호출해 작업을 수행합니다.
        random.seed(self._seed)
        # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
        self._output_dir.mkdir(parents=True, exist_ok=True)
        # load_indexed_chunks()의 반환값을 chunks에 대입합니다.
        chunks = load_indexed_chunks(self._database_path)
        # self._write_document_catalog()의 반환값을 catalog_path에 대입합니다.
        catalog_path = self._write_document_catalog(chunks)

        # FTS5 is materialized first so its RSS sample does not include the vector index.
        # 오른쪽 식을 계산한 값을 artifact_dir에 대입합니다.
        artifact_dir = self._output_dir / "indexes"
        # FTS5SearchRetriever()의 반환값을 fts5에 대입합니다.
        fts5 = FTS5SearchRetriever(chunks, artifact_dir=artifact_dir)
        # VectorSearchRetriever()의 반환값을 vector에 대입합니다.
        vector = VectorSearchRetriever(chunks, artifact_dir=artifact_dir)
        # HybridRRFSearchRetriever()의 반환값을 hybrid에 대입합니다.
        hybrid = HybridRRFSearchRetriever(vector, fts5, rrf_k=self._rrf_k)
        # retrievers에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
        retrievers: tuple[BenchmarkRetriever, ...] = (vector, fts5, hybrid)

        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # self._measure()의 반환값을 query_runs에 대입합니다.
            query_runs = self._measure(retrievers)
            # self._per_query_rows()의 반환값을 per_query_rows에 대입합니다.
            per_query_rows = self._per_query_rows(query_runs)
            # self._summary_rows()의 반환값을 summary_rows에 대입합니다.
            summary_rows = self._summary_rows(query_runs, retrievers)
            # self._query_type_rows()의 반환값을 query_type_rows에 대입합니다.
            query_type_rows = self._query_type_rows(query_runs, retrievers)
            # max()의 반환값을 reporting_top_k에 대입합니다.
            reporting_top_k = max(self._top_k_values)
            # create_benchmark_charts()의 반환값을 chart_paths에 대입합니다.
            chart_paths = create_benchmark_charts(
                summary_rows,
                query_type_rows,
                charts_dir=self._output_dir / "charts",
                reporting_top_k=reporting_top_k,
                per_query_rows=per_query_rows,
            )
            # self._write_reports()의 반환값을 paths에 대입합니다.
            paths = self._write_reports(
                per_query_rows=per_query_rows,
                summary_rows=summary_rows,
                query_type_rows=query_type_rows,
                chunks=chunks,
                chart_paths=chart_paths,
                reporting_top_k=reporting_top_k,
            )
        # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
        finally:
            # 사용하던 연결이나 자원을 닫습니다.
            fts5.close()

        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return BenchmarkRunResult(
            summary_path=paths["summary"],
            per_query_path=paths["per_query"],
            by_query_type_path=paths["by_query_type"],
            report_path=paths["report"],
            chart_paths=chart_paths,
            catalog_path=catalog_path,
            summary_rows=tuple(summary_rows),
            query_type_rows=tuple(query_type_rows),
        )

    # _measure(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: retrievers.
    # 반환 타입 힌트: tuple[_QueryRun, ...].
    def _measure(self, retrievers: Sequence[BenchmarkRetriever]) -> tuple[_QueryRun, ...]:
        # max()의 반환값을 warmup_top_k에 대입합니다.
        warmup_top_k = max(self._top_k_values)
        # tuple()의 반환값을 warmup_set에 대입합니다.
        warmup_set = tuple(
            self._queries[index % len(self._queries)] for index in range(self._warmup_queries)
        )
        # for 반복문: 대상의 항목을 하나씩 retriever에 대입하며 아래 블록을 실행합니다.
        for retriever in retrievers:
            # for 반복문: 대상의 항목을 하나씩 query에 대입하며 아래 블록을 실행합니다.
            for query in warmup_set:
                # retriever.search()을 호출해 작업을 수행합니다.
                retriever.search(query.query, top_k=warmup_top_k)

        # query_runs에 리스트(순서가 있고 수정 가능)을 대입합니다.
        query_runs: list[_QueryRun] = []
        # for 반복문: 대상의 항목을 하나씩 top_k에 대입하며 아래 블록을 실행합니다.
        for top_k in self._top_k_values:
            # for 반복문: 대상의 항목을 하나씩 retriever에 대입하며 아래 블록을 실행합니다.
            for retriever in retrievers:
                # for 반복문: 대상의 항목을 하나씩 query에 대입하며 아래 블록을 실행합니다.
                for query in self._queries:
                    # tuple()의 반환값을 traces에 대입합니다.
                    traces = tuple(
                        retriever.search_with_trace(query.query, top_k=top_k)
                        for _ in range(self._repeats)
                    )
                    # mean_metrics()의 반환값을 metrics에 대입합니다.
                    metrics = mean_metrics(
                        [
                            quality_metrics(trace.results, query.relevant_document_ids)
                            for trace in traces
                        ]
                    )
                    # 리스트 끝에 항목 하나를 추가합니다.
                    query_runs.append(
                        _QueryRun(
                            retriever=retriever.name,
                            top_k=top_k,
                            query=query,
                            traces=traces,
                            quality=metrics,
                        )
                    )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return tuple(query_runs)

    # _per_query_rows(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: query_runs.
    # 반환 타입 힌트: list[dict[str, Any]].
    def _per_query_rows(self, query_runs: Sequence[_QueryRun]) -> list[dict[str, Any]]:
        # rows에 리스트(순서가 있고 수정 가능)을 대입합니다.
        rows: list[dict[str, Any]] = []
        # for 반복문: 대상의 항목을 하나씩 run에 대입하며 아래 블록을 실행합니다.
        for run in query_runs:
            # 오른쪽 식을 계산한 값을 first_trace에 대입합니다.
            first_trace = run.traces[0]
            # 오른쪽 식을 계산한 값을 search_ms에 대입합니다.
            # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
            search_ms = [trace.search_ms for trace in run.traces]
            # 오른쪽 식을 계산한 값을 total_ms에 대입합니다.
            # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
            total_ms = [trace.total_response_ms for trace in run.traces]
            # 오른쪽 식을 계산한 값을 embedding_ms에 대입합니다.
            # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
            embedding_ms = [trace.embedding_ms for trace in run.traces]
            # row에 딕셔너리(키와 값의 쌍)을 대입합니다.
            row: dict[str, Any] = {
                "retriever": run.retriever,
                "top_k": run.top_k,
                "query_id": run.query.query_id,
                "query_type": run.query.query_type,
                "query": run.query.query,
                "relevant_document_ids": json.dumps(
                    run.query.relevant_document_ids, ensure_ascii=False
                ),
                "retrieved_document_ids": json.dumps(
                    _unique_document_ids(first_trace), ensure_ascii=False
                ),
                "repeat_count": len(run.traces),
                **run.quality,
                "embedding_avg_ms": fmean(embedding_ms),
                "embedding_p95_ms": percentile(embedding_ms, 95),
                "search_avg_ms": fmean(search_ms),
                "search_p50_ms": percentile(search_ms, 50),
                "search_p95_ms": percentile(search_ms, 95),
                "total_response_avg_ms": fmean(total_ms),
                "total_response_p50_ms": percentile(total_ms, 50),
                "total_response_p95_ms": percentile(total_ms, 95),
            }
            # 리스트 끝에 항목 하나를 추가합니다.
            rows.append(row)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return rows

    # _summary_rows(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: query_runs, retrievers.
    # 반환 타입 힌트: list[dict[str, Any]].
    def _summary_rows(
        self,
        query_runs: Sequence[_QueryRun],
        retrievers: Sequence[BenchmarkRetriever],
    ) -> list[dict[str, Any]]:
        # 오른쪽 식을 계산한 값을 costs에 대입합니다.
        # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
        costs = {retriever.name: retriever.index_cost for retriever in retrievers}
        # rows에 리스트(순서가 있고 수정 가능)을 대입합니다.
        rows: list[dict[str, Any]] = []
        # for 반복문: 대상의 항목을 하나씩 top_k에 대입하며 아래 블록을 실행합니다.
        for top_k in self._top_k_values:
            # for 반복문: 대상의 항목을 하나씩 retriever_name에 대입하며 아래 블록을 실행합니다.
            for retriever_name in (VECTOR_NAME, FTS5_NAME, RRF_NAME):
                # 오른쪽 식을 계산한 값을 selected에 대입합니다.
                # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
                selected = [
                    run
                    for run in query_runs
                    if run.top_k == top_k and run.retriever == retriever_name
                ]
                # 리스트 끝에 항목 하나를 추가합니다.
                rows.append(self._aggregate_runs(selected, costs[retriever_name], query_type=None))
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return rows

    # _query_type_rows(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: query_runs, retrievers.
    # 반환 타입 힌트: list[dict[str, Any]].
    def _query_type_rows(
        self,
        query_runs: Sequence[_QueryRun],
        retrievers: Sequence[BenchmarkRetriever],
    ) -> list[dict[str, Any]]:
        # 오른쪽 식을 계산한 값을 costs에 대입합니다.
        # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
        costs = {retriever.name: retriever.index_cost for retriever in retrievers}
        # rows에 리스트(순서가 있고 수정 가능)을 대입합니다.
        rows: list[dict[str, Any]] = []
        # for 반복문: 대상의 항목을 하나씩 top_k에 대입하며 아래 블록을 실행합니다.
        for top_k in self._top_k_values:
            # for 반복문: 대상의 항목을 하나씩 query_type에 대입하며 아래 블록을 실행합니다.
            for query_type in ("keyword", "semantic", "hybrid"):
                # for 반복문: 대상의 항목을 하나씩 retriever_name에 대입하며 아래 블록을
                # 실행합니다.
                for retriever_name in (VECTOR_NAME, FTS5_NAME, RRF_NAME):
                    # 오른쪽 식을 계산한 값을 selected에 대입합니다.
                    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로
                    # 모읍니다.
                    selected = [
                        run
                        for run in query_runs
                        if run.top_k == top_k
                        and run.retriever == retriever_name
                        and run.query.query_type == query_type
                    ]
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: selected.
                    if selected:
                        # 리스트 끝에 항목 하나를 추가합니다.
                        rows.append(
                            self._aggregate_runs(
                                selected,
                                costs[retriever_name],
                                query_type=query_type,
                            )
                        )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return rows

    # _aggregate_runs(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: runs, cost, query_type.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: dict[str, Any].
    def _aggregate_runs(
        self,
        runs: Sequence[_QueryRun],
        cost: Any,
        *,
        query_type: str | None,
    ) -> dict[str, Any]:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not runs.
        if not runs:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("집계할 번치마크 실행이 없습니다.")
        # 오른쪽 식을 계산한 값을 search_times에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        search_times = [trace.search_ms for run in runs for trace in run.traces]
        # 오른쪽 식을 계산한 값을 response_times에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        response_times = [trace.total_response_ms for run in runs for trace in run.traces]
        # 오른쪽 식을 계산한 값을 embedding_times에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        embedding_times = [trace.embedding_ms for run in runs for trace in run.traces]
        # latency_metrics()의 반환값을 search_latency에 대입합니다.
        search_latency = latency_metrics(search_times)
        # latency_metrics()의 반환값을 response_latency에 대입합니다.
        response_latency = latency_metrics(response_times)
        # mean_metrics()의 반환값을 metrics에 대입합니다.
        metrics = mean_metrics([run.quality for run in runs])
        # row에 딕셔너리(키와 값의 쌍)을 대입합니다.
        row: dict[str, Any] = {
            "retriever": runs[0].retriever,
            "top_k": runs[0].top_k,
            "query_type": query_type or "all",
            "query_count": len(runs),
            "repeat_count": self._repeats,
            **metrics,
            **search_latency,
            "qps": response_latency["qps"],
            "embedding_avg_ms": fmean(embedding_times),
            "embedding_p50_ms": percentile(embedding_times, 50),
            "embedding_p95_ms": percentile(embedding_times, 95),
            "total_response_avg_ms": response_latency["latency_avg_ms"],
            "total_response_p50_ms": response_latency["latency_p50_ms"],
            "total_response_p95_ms": response_latency["latency_p95_ms"],
            "total_response_min_ms": response_latency["latency_min_ms"],
            "total_response_max_ms": response_latency["latency_max_ms"],
            "index_build_ms": cost.build_ms,
            "index_size_mb": cost.size_mb,
            "process_memory_mb": cost.process_memory_mb,
            "index_artifact": (
                str(cost.artifact_path) if cost.artifact_path else "shared vector + fts5"
            ),
        }
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return row

    # _write_reports(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: per_query_rows, summary_rows, query_type_rows, chunks, chart_paths, reporting_top_k.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: dict[str, Path].
    def _write_reports(
        self,
        *,
        per_query_rows: Sequence[dict[str, Any]],
        summary_rows: Sequence[dict[str, Any]],
        query_type_rows: Sequence[dict[str, Any]],
        chunks: Sequence[IndexedChunk],
        chart_paths: Sequence[Path],
        reporting_top_k: int,
    ) -> dict[str, Path]:
        # 오른쪽 식을 계산한 값을 summary_path에 대입합니다.
        summary_path = self._output_dir / "benchmark_summary.csv"
        # 오른쪽 식을 계산한 값을 per_query_path에 대입합니다.
        per_query_path = self._output_dir / "benchmark_per_query.csv"
        # 오른쪽 식을 계산한 값을 by_query_type_path에 대입합니다.
        by_query_type_path = self._output_dir / "benchmark_by_query_type.csv"
        # 오른쪽 식을 계산한 값을 report_path에 대입합니다.
        report_path = self._output_dir / "benchmark_report.json"
        # _write_csv()을 호출해 작업을 수행합니다.
        _write_csv(summary_path, summary_rows)
        # _write_csv()을 호출해 작업을 수행합니다.
        _write_csv(per_query_path, per_query_rows)
        # _write_csv()을 호출해 작업을 수행합니다.
        _write_csv(by_query_type_path, query_type_rows)

        # 오른쪽 식을 계산한 값을 indexed_document_ids에 대입합니다.
        # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
        indexed_document_ids = {chunk.document_id for chunk in chunks}
        # sorted()의 반환값을 unknown_relevant_ids에 대입합니다.
        unknown_relevant_ids = sorted(
            {
                document_id
                for query in self._queries
                for document_id in query.relevant_document_ids
                if document_id not in indexed_document_ids
            }
        )
        # report에 딕셔너리(키와 값의 쌍)을 대입합니다.
        report = {
            "metadata": {
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "database_path": str(self._database_path),
                "query_count": len(self._queries),
                "indexed_document_count": len(indexed_document_ids),
                "indexed_chunk_count": len(chunks),
                "top_k_values": list(self._top_k_values),
                "reporting_top_k": reporting_top_k,
                "repeats": self._repeats,
                "warmup_queries": self._warmup_queries,
                "rrf_k": self._rrf_k,
                "random_seed": self._seed,
                "unknown_relevant_document_ids": unknown_relevant_ids,
            },
            "summary": list(summary_rows),
            "by_query_type": list(query_type_rows),
            "per_query": list(per_query_rows),
            "charts": [str(path) for path in chart_paths],
        }
        # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return {
            "summary": summary_path,
            "per_query": per_query_path,
            "by_query_type": by_query_type_path,
            "report": report_path,
        }

    # _write_document_catalog(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: chunks.
    # 반환 타입 힌트: Path.
    def _write_document_catalog(self, chunks: Sequence[IndexedChunk]) -> Path:
        # 오른쪽 식을 계산한 값을 path에 대입합니다.
        path = self._output_dir / "document_catalog.csv"
        # 오른쪽 식을 계산한 값을 rows에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        rows = [
            {
                "document_id": chunk.document_id,
                "chunk_id": chunk.chunk_id,
                "source_path": chunk.source_path,
                "content_preview": chunk.content.replace("\n", " ")[:200],
            }
            for chunk in chunks
        ]
        # _write_csv()을 호출해 작업을 수행합니다.
        _write_csv(path, rows)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return path


# _unique_document_ids(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: trace.
# 반환 타입 힌트: list[str].
def _unique_document_ids(trace: SearchTrace) -> list[str]:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return list(dict.fromkeys(result["document_id"] for result in trace.results))


# _write_csv(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, rows.
# 반환 타입 힌트: 별도 결과 없음(None).
def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not rows.
    if not rows:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError(f"쓸 번치마크 행이 없습니다: {path.name}")
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        # csv.DictWriter()의 반환값을 writer에 대입합니다.
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        # writer.writeheader()을 호출해 작업을 수행합니다.
        writer.writeheader()
        # writer.writerows()을 호출해 작업을 수행합니다.
        writer.writerows(rows)


# _json_default(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value.
# 반환 타입 힌트: object.
def _json_default(value: object) -> object:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(value, Path).
    if isinstance(value, Path):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return str(value)
    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
    raise TypeError(f"JSON으로 직렬화할 수 없는 값입니다: {type(value).__name__}")

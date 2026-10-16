# 파이썬 공부 | scripts/app/rag/benchmark/visualization.py
# Matplotlib으로 검색 평가 결과를 그래프로 그립니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Matplotlib charts for the local RAG benchmark report."""

from __future__ import annotations

import random
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path
from typing import Any

from app.rag.benchmark.retrievers import FTS5_NAME, RRF_NAME, VECTOR_NAME

# METHOD_ORDER에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
METHOD_ORDER = (VECTOR_NAME, FTS5_NAME, RRF_NAME)
# METHOD_COLORS에 딕셔너리(키와 값의 쌍)을 대입합니다.
METHOD_COLORS = {
    VECTOR_NAME: "#1F77B4",  # blue
    FTS5_NAME: "#FF7F0E",  # orange
    RRF_NAME: "#2CA02C",  # green
}
# QUERY_TYPES에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
QUERY_TYPES = ("keyword", "semantic", "hybrid")


# create_benchmark_charts(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: summary_rows, query_type_rows, charts_dir, reporting_top_k, per_query_rows.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: tuple[Path, ...].
def create_benchmark_charts(
    summary_rows: Sequence[dict[str, Any]],
    query_type_rows: Sequence[dict[str, Any]],
    *,
    charts_dir: Path,
    reporting_top_k: int,
    per_query_rows: Sequence[dict[str, Any]] = (),
) -> tuple[Path, ...]:
    """Create the five portfolio-ready PNG charts required by the benchmark."""

    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # import_module()의 반환값을 matplotlib에 대입합니다.
        matplotlib = import_module("matplotlib")
        # matplotlib.use()을 호출해 작업을 수행합니다.
        matplotlib.use("Agg")
        # import_module()의 반환값을 font_manager에 대입합니다.
        font_manager = import_module("matplotlib.font_manager")
        # import_module()의 반환값을 plt에 대입합니다.
        plt = import_module("matplotlib.pyplot")
    # ImportError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except ImportError as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise RuntimeError(
            '그래프 생성에는 matplotlib이 필요합니다. pip install -e ".[benchmark]"를 실행하세요.'
        ) from error

    # _configure_korean_font()을 호출해 작업을 수행합니다.
    _configure_korean_font(plt, font_manager)
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    charts_dir.mkdir(parents=True, exist_ok=True)
    # _rows_for_top_k()의 반환값을 selected에 대입합니다.
    selected = _rows_for_top_k(summary_rows, reporting_top_k)
    # _require_all_methods()을 호출해 작업을 수행합니다.
    _require_all_methods(selected, "summary")

    # paths에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    paths: tuple[Path, ...] = (
        charts_dir / "retrieval_quality_comparison.png",
        charts_dir / "latency_comparison.png",
        charts_dir / "query_type_comparison.png",
        charts_dir / "accuracy_latency_tradeoff.png",
        charts_dir / "index_cost_comparison.png",
    )

    # _quality_chart()을 호출해 작업을 수행합니다.
    _quality_chart(plt, selected, paths[0])
    # _latency_chart()을 호출해 작업을 수행합니다.
    _latency_chart(plt, selected, paths[1])
    # _query_type_chart()을 호출해 작업을 수행합니다.
    _query_type_chart(plt, query_type_rows, reporting_top_k, paths[2])
    # _tradeoff_chart()을 호출해 작업을 수행합니다.
    _tradeoff_chart(plt, selected, paths[3])
    # _index_cost_chart()을 호출해 작업을 수행합니다.
    _index_cost_chart(plt, selected, paths[4])
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: per_query_rows.
    if per_query_rows:
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        paths += _line_charts(plt, summary_rows, per_query_rows, charts_dir, reporting_top_k)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return paths


# _graph_paper(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: axis.
# 반환 타입 힌트: 별도 결과 없음(None).
def _graph_paper(axis: Any) -> None:
    # import_module()의 반환값을 ticker에 대입합니다.
    ticker = import_module("matplotlib.ticker")
    # axis.set_facecolor()을 호출해 작업을 수행합니다.
    axis.set_facecolor("white")
    # axis.set_axisbelow()을 호출해 작업을 수행합니다.
    axis.set_axisbelow(True)
    # axis.xaxis.set_minor_locator()을 호출해 작업을 수행합니다.
    axis.xaxis.set_minor_locator(ticker.AutoMinorLocator(4))
    # axis.yaxis.set_minor_locator()을 호출해 작업을 수행합니다.
    axis.yaxis.set_minor_locator(ticker.AutoMinorLocator(4))
    # axis.grid()을 호출해 작업을 수행합니다.
    axis.grid(which="major", color="#58c8f0", linewidth=0.7)
    # axis.grid()을 호출해 작업을 수행합니다.
    axis.grid(which="minor", color="#a5e5fa", linewidth=0.4)
    # for 반복문: 대상의 항목을 하나씩 spine에 대입하며 아래 블록을 실행합니다.
    for spine in axis.spines.values():
        # spine.set_color()을 호출해 작업을 수행합니다.
        spine.set_color("#58c8f0")
    # axis.legend()을 호출해 작업을 수행합니다.
    axis.legend(loc="best", framealpha=0.95)


# _line_charts(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: plt, summaries, per_query, directory, top_k.
# 반환 타입 힌트: tuple[Path, ...].
def _line_charts(
    plt: Any,
    summaries: Sequence[dict[str, Any]],
    per_query: Sequence[dict[str, Any]],
    directory: Path,
    top_k: int,
) -> tuple[Path, ...]:
    """Connect measured observations; no fitted curves or fabricated monotonic quality."""
    # paths에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    paths = (
        directory / "recall_by_top_k.png",
        directory / "quality_convergence.png",
        directory / "cumulative_response_time.png",
    )
    # 언패킹: 오른쪽 결과를 순서대로 (figure, axis)에 나누어 담습니다.
    figure, axis = plt.subplots(figsize=(9, 5.5))
    # for 반복문: 대상의 항목을 하나씩 method에 대입하며 아래 블록을 실행합니다.
    for method in METHOD_ORDER:
        # sorted()의 반환값을 rows에 대입합니다.
        rows = sorted(
            (row for row in summaries if row["retriever"] == method),
            key=lambda row: int(row["top_k"]),
        )
        # axis.plot()을 호출해 작업을 수행합니다.
        axis.plot(
            [int(row["top_k"]) for row in rows],
            [float(row[f"recall_at_{row['top_k']}"]) * 100 for row in rows],
            "o-",
            color=METHOD_COLORS[method],
            label=method,
            linewidth=1.8,
        )
    # axis.set()을 호출해 작업을 수행합니다.
    axis.set(
        title="검색 결과 수에 따른 Recall · 데모 평가",
        xlabel="검색 결과 수 (top_k)",
        ylabel="Recall (%)",
        ylim=(0, 105),
    )
    # axis.set_xticks()을 호출해 작업을 수행합니다.
    axis.set_xticks(sorted({int(row["top_k"]) for row in summaries}))
    # _graph_paper()을 호출해 작업을 수행합니다.
    _graph_paper(axis)
    # _save()을 호출해 작업을 수행합니다.
    _save(figure, paths[0])

    # 오른쪽 식을 계산한 값을 selected에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    selected = [row for row in per_query if int(row["top_k"]) == top_k]
    # sorted()의 반환값을 query_ids에 대입합니다.
    query_ids = sorted({str(row["query_id"]) for row in selected})
    # random.Random(42).shuffle()을 호출해 작업을 수행합니다.
    random.Random(42).shuffle(query_ids)
    # for 반복문: 대상의 항목을 하나씩 (metric, path, title, ylabel)에 대입하며 아래 블록을
    # 실행합니다.
    for metric, path, title, ylabel in (
        ("recall_at_5", paths[1], "누적 평균 Recall@5", "누적 평균 Recall@5 (%)"),
        ("total_response_avg_ms", paths[2], "누적 응답 시간", "누적 응답 시간 (ms)"),
    ):
        # 언패킹: 오른쪽 결과를 순서대로 (figure, axis)에 나누어 담습니다.
        figure, axis = plt.subplots(figsize=(9, 5.5))
        # for 반복문: 대상의 항목을 하나씩 method에 대입하며 아래 블록을 실행합니다.
        for method in METHOD_ORDER:
            # 오른쪽 식을 계산한 값을 by_id에 대입합니다.
            # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
            by_id = {str(row["query_id"]): row for row in selected if row["retriever"] == method}
            # cumulative에 숫자 등 고정된 값을 대입합니다.
            cumulative = 0.0
            # values에 리스트(순서가 있고 수정 가능)을 대입합니다.
            values = []
            # for 반복문: 대상의 항목을 하나씩 (n, query_id)에 대입하며 아래 블록을 실행합니다.
            for n, query_id in enumerate(query_ids, 1):
                # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                cumulative += float(by_id[query_id][metric])
                # 리스트 끝에 항목 하나를 추가합니다.
                values.append(cumulative * 100 / n if metric == "recall_at_5" else cumulative)
            # axis.plot()을 호출해 작업을 수행합니다.
            axis.plot(
                range(1, len(values) + 1),
                values,
                "o-",
                markevery=sorted({*range(19, len(values), 20), len(values) - 1}),
                markersize=4,
                linewidth=1.6,
                color=METHOD_COLORS[method],
                label=method,
            )
        # axis.set()을 호출해 작업을 수행합니다.
        axis.set(
            title=f"{title} · 데모 {len(query_ids)}문항 / top_k={top_k}",
            xlabel="평가 질문 수 (개)",
            ylabel=ylabel,
            xlim=(0, len(query_ids)),
        )
        # axis.set_xticks()을 호출해 작업을 수행합니다.
        axis.set_xticks([*range(0, len(query_ids), 20), len(query_ids)])
        # axis.set_ylim()을 호출해 작업을 수행합니다.
        axis.set_ylim(bottom=0)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: metric == 'recall_at_5'.
        if metric == "recall_at_5":
            # axis.set_ylim()을 호출해 작업을 수행합니다.
            axis.set_ylim(0, 105)
        # _graph_paper()을 호출해 작업을 수행합니다.
        _graph_paper(axis)
        # figure.text()을 호출해 작업을 수행합니다.
        figure.text(
            0.5,
            0.01,
            f"동일 질문 순서(seed=42) · 질문별 {selected[0]['repeat_count']}회 평균 · 보간 없음",
            ha="center",
            fontsize=9,
        )
        # figure.tight_layout()을 호출해 작업을 수행합니다.
        figure.tight_layout(rect=(0, 0.035, 1, 1))
        # figure.savefig()을 호출해 작업을 수행합니다.
        figure.savefig(path, dpi=180, bbox_inches="tight")
        # 사용하던 연결이나 자원을 닫습니다.
        plt.close(figure)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return paths


# _quality_chart(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: plt, rows, path.
# 반환 타입 힌트: 별도 결과 없음(None).
def _quality_chart(plt: Any, rows: Sequence[dict[str, Any]], path: Path) -> None:
    # metrics에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    metrics = (("recall_at_5", "Recall@5"), ("mrr_at_10", "MRR@10"), ("ndcg_at_10", "nDCG@10"))
    # 언패킹: 오른쪽 결과를 순서대로 (figure, axis)에 나누어 담습니다.
    figure, axis = plt.subplots(figsize=(10, 6))
    # list()의 반환값을 positions에 대입합니다.
    positions = list(range(len(metrics)))
    # width에 숫자 등 고정된 값을 대입합니다.
    width = 0.22
    # for 반복문: 대상의 항목을 하나씩 (index, method)에 대입하며 아래 블록을 실행합니다.
    for index, method in enumerate(METHOD_ORDER):
        # _row_for_method()의 반환값을 row에 대입합니다.
        row = _row_for_method(rows, method)
        # 오른쪽 식을 계산한 값을 offset에 대입합니다.
        offset = (index - 1) * width
        # axis.bar()을 호출해 작업을 수행합니다.
        axis.bar(
            [position + offset for position in positions],
            [float(row[key]) for key, _ in metrics],
            width=width,
            label=method,
            color=METHOD_COLORS[method],
        )
    # axis.set_title()을 호출해 작업을 수행합니다.
    axis.set_title("검색 품질 비교")
    # axis.set_ylabel()을 호출해 작업을 수행합니다.
    axis.set_ylabel("점수")
    # axis.set_ylim()을 호출해 작업을 수행합니다.
    axis.set_ylim(0, 1.05)
    # axis.set_xticks()을 호출해 작업을 수행합니다.
    axis.set_xticks(positions, [label for _, label in metrics])
    # axis.legend()을 호출해 작업을 수행합니다.
    axis.legend()
    # axis.grid()을 호출해 작업을 수행합니다.
    axis.grid(axis="y", alpha=0.25)
    # _save()을 호출해 작업을 수행합니다.
    _save(figure, path)


# _latency_chart(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: plt, rows, path.
# 반환 타입 힌트: 별도 결과 없음(None).
def _latency_chart(plt: Any, rows: Sequence[dict[str, Any]], path: Path) -> None:
    # metrics에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    metrics = (
        ("latency_avg_ms", "평균"),
        ("latency_p50_ms", "P50"),
        ("latency_p95_ms", "P95"),
    )
    # 언패킹: 오른쪽 결과를 순서대로 (figure, axis)에 나누어 담습니다.
    figure, axis = plt.subplots(figsize=(10, 6))
    # list()의 반환값을 positions에 대입합니다.
    positions = list(range(len(metrics)))
    # width에 숫자 등 고정된 값을 대입합니다.
    width = 0.22
    # for 반복문: 대상의 항목을 하나씩 (index, method)에 대입하며 아래 블록을 실행합니다.
    for index, method in enumerate(METHOD_ORDER):
        # _row_for_method()의 반환값을 row에 대입합니다.
        row = _row_for_method(rows, method)
        # axis.bar()을 호출해 작업을 수행합니다.
        axis.bar(
            [position + (index - 1) * width for position in positions],
            [float(row[key]) for key, _ in metrics],
            width=width,
            label=method,
            color=METHOD_COLORS[method],
        )
    # axis.set_title()을 호출해 작업을 수행합니다.
    axis.set_title("검색 지연시간 비교")
    # axis.set_ylabel()을 호출해 작업을 수행합니다.
    axis.set_ylabel("ms")
    # axis.set_xticks()을 호출해 작업을 수행합니다.
    axis.set_xticks(positions, [label for _, label in metrics])
    # axis.legend()을 호출해 작업을 수행합니다.
    axis.legend()
    # axis.grid()을 호출해 작업을 수행합니다.
    axis.grid(axis="y", alpha=0.25)
    # _save()을 호출해 작업을 수행합니다.
    _save(figure, path)


# _query_type_chart(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: plt, rows, reporting_top_k, path.
# 반환 타입 힌트: 별도 결과 없음(None).
def _query_type_chart(
    plt: Any,
    rows: Sequence[dict[str, Any]],
    reporting_top_k: int,
    path: Path,
) -> None:
    # _rows_for_top_k()의 반환값을 selected에 대입합니다.
    selected = _rows_for_top_k(rows, reporting_top_k)
    # 언패킹: 오른쪽 결과를 순서대로 (figure, axis)에 나누어 담습니다.
    figure, axis = plt.subplots(figsize=(10, 6))
    # list()의 반환값을 positions에 대입합니다.
    positions = list(range(len(QUERY_TYPES)))
    # width에 숫자 등 고정된 값을 대입합니다.
    width = 0.22
    # for 반복문: 대상의 항목을 하나씩 (method_index, method)에 대입하며 아래 블록을 실행합니다.
    for method_index, method in enumerate(METHOD_ORDER):
        # values에 리스트(순서가 있고 수정 가능)을 대입합니다.
        values: list[float] = []
        # for 반복문: 대상의 항목을 하나씩 query_type에 대입하며 아래 블록을 실행합니다.
        for query_type in QUERY_TYPES:
            # next()의 반환값을 row에 대입합니다.
            row = next(
                (
                    candidate
                    for candidate in selected
                    if candidate["retriever"] == method and candidate["query_type"] == query_type
                ),
                None,
            )
            # 리스트 끝에 항목 하나를 추가합니다.
            values.append(float(row["recall_at_5"]) if row is not None else 0.0)
        # axis.bar()을 호출해 작업을 수행합니다.
        axis.bar(
            [position + (method_index - 1) * width for position in positions],
            values,
            width=width,
            label=method,
            color=METHOD_COLORS[method],
        )
    # axis.set_title()을 호출해 작업을 수행합니다.
    axis.set_title("쿼리 유형별 Recall@5")
    # axis.set_ylabel()을 호출해 작업을 수행합니다.
    axis.set_ylabel("Recall@5")
    # axis.set_ylim()을 호출해 작업을 수행합니다.
    axis.set_ylim(0, 1.05)
    # axis.set_xticks()을 호출해 작업을 수행합니다.
    axis.set_xticks(positions, ["Keyword", "Semantic", "Hybrid"])
    # axis.legend()을 호출해 작업을 수행합니다.
    axis.legend()
    # axis.grid()을 호출해 작업을 수행합니다.
    axis.grid(axis="y", alpha=0.25)
    # _save()을 호출해 작업을 수행합니다.
    _save(figure, path)


# _tradeoff_chart(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: plt, rows, path.
# 반환 타입 힌트: 별도 결과 없음(None).
def _tradeoff_chart(plt: Any, rows: Sequence[dict[str, Any]], path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (figure, axis)에 나누어 담습니다.
    figure, axis = plt.subplots(figsize=(8, 6))
    # for 반복문: 대상의 항목을 하나씩 method에 대입하며 아래 블록을 실행합니다.
    for method in METHOD_ORDER:
        # _row_for_method()의 반환값을 row에 대입합니다.
        row = _row_for_method(rows, method)
        # float()의 반환값을 x에 대입합니다.
        x = float(row["latency_avg_ms"])
        # float()의 반환값을 y에 대입합니다.
        y = float(row["recall_at_5"])
        # axis.scatter()을 호출해 작업을 수행합니다.
        axis.scatter(x, y, s=120, color=METHOD_COLORS[method], label=method)
        # axis.annotate()을 호출해 작업을 수행합니다.
        axis.annotate(method, (x, y), xytext=(7, 7), textcoords="offset points")
    # axis.set_title()을 호출해 작업을 수행합니다.
    axis.set_title("정확도·속도 트레이드오프")
    # axis.set_xlabel()을 호출해 작업을 수행합니다.
    axis.set_xlabel("평균 검색 지연시간 (ms)")
    # axis.set_ylabel()을 호출해 작업을 수행합니다.
    axis.set_ylabel("Recall@5")
    # axis.set_ylim()을 호출해 작업을 수행합니다.
    axis.set_ylim(0, 1.05)
    # axis.grid()을 호출해 작업을 수행합니다.
    axis.grid(alpha=0.25)
    # axis.legend()을 호출해 작업을 수행합니다.
    axis.legend()
    # _save()을 호출해 작업을 수행합니다.
    _save(figure, path)


# _index_cost_chart(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: plt, rows, path.
# 반환 타입 힌트: 별도 결과 없음(None).
def _index_cost_chart(plt: Any, rows: Sequence[dict[str, Any]], path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (figure, axes)에 나누어 담습니다.
    figure, axes = plt.subplots(1, 2, figsize=(12, 5))
    # list()의 반환값을 methods에 대입합니다.
    methods = list(METHOD_ORDER)
    # 오른쪽 식을 계산한 값을 colors에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    colors = [METHOD_COLORS[method] for method in methods]
    # 오른쪽 식을 계산한 값을 build_values에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    build_values = [float(_row_for_method(rows, method)["index_build_ms"]) for method in methods]
    # 오른쪽 식을 계산한 값을 size_values에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    size_values = [float(_row_for_method(rows, method)["index_size_mb"]) for method in methods]
    # axes[0].bar()을 호출해 작업을 수행합니다.
    axes[0].bar(methods, build_values, color=colors)
    # axes[0].set_title()을 호출해 작업을 수행합니다.
    axes[0].set_title("인덱스 생성 시간")
    # axes[0].set_ylabel()을 호출해 작업을 수행합니다.
    axes[0].set_ylabel("ms")
    # axes[0].tick_params()을 호출해 작업을 수행합니다.
    axes[0].tick_params(axis="x", rotation=15)
    # axes[0].grid()을 호출해 작업을 수행합니다.
    axes[0].grid(axis="y", alpha=0.25)
    # axes[1].bar()을 호출해 작업을 수행합니다.
    axes[1].bar(methods, size_values, color=colors)
    # axes[1].set_title()을 호출해 작업을 수행합니다.
    axes[1].set_title("인덱스 크기")
    # axes[1].set_ylabel()을 호출해 작업을 수행합니다.
    axes[1].set_ylabel("MB")
    # axes[1].tick_params()을 호출해 작업을 수행합니다.
    axes[1].tick_params(axis="x", rotation=15)
    # axes[1].grid()을 호출해 작업을 수행합니다.
    axes[1].grid(axis="y", alpha=0.25)
    # _save()을 호출해 작업을 수행합니다.
    _save(figure, path)


# _configure_korean_font(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: plt, font_manager.
# 반환 타입 힌트: 별도 결과 없음(None).
def _configure_korean_font(plt: Any, font_manager: Any) -> None:
    # 오른쪽 식을 계산한 값을 available에 대입합니다.
    # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
    available = {font.name for font in font_manager.fontManager.ttflist}
    # candidates에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    candidates = ("Malgun Gothic", "AppleGothic", "Noto Sans CJK KR", "NanumGothic", "DejaVu Sans")
    # next()의 반환값을 plt.rcParams['font.family']에 대입합니다.
    plt.rcParams["font.family"] = next(
        (candidate for candidate in candidates if candidate in available), "DejaVu Sans"
    )
    # plt.rcParams['axes.unicode_minus']을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    plt.rcParams["axes.unicode_minus"] = False


# _rows_for_top_k(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: rows, top_k.
# 반환 타입 힌트: list[dict[str, Any]].
def _rows_for_top_k(rows: Sequence[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    return [row for row in rows if int(row["top_k"]) == top_k]


# _require_all_methods(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: rows, label.
# 반환 타입 힌트: 별도 결과 없음(None).
def _require_all_methods(rows: Sequence[dict[str, Any]], label: str) -> None:
    # 오른쪽 식을 계산한 값을 present에 대입합니다.
    # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
    present = {str(row["retriever"]) for row in rows}
    # 오른쪽 식을 계산한 값을 missing에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    missing = [method for method in METHOD_ORDER if method not in present]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: missing.
    if missing:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError(f"{label} 차트에 필요한 검색 방식이 빠졌습니다: {', '.join(missing)}")


# _row_for_method(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: rows, method.
# 반환 타입 힌트: dict[str, Any].
def _row_for_method(rows: Sequence[dict[str, Any]], method: str) -> dict[str, Any]:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return next(row for row in rows if row["retriever"] == method)


# _save(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: figure, path.
# 반환 타입 힌트: 별도 결과 없음(None).
def _save(figure: Any, path: Path) -> None:
    # figure.tight_layout()을 호출해 작업을 수행합니다.
    figure.tight_layout()
    # figure.savefig()을 호출해 작업을 수행합니다.
    figure.savefig(path, dpi=180, bbox_inches="tight")
    # 사용하던 연결이나 자원을 닫습니다.
    import_module("matplotlib.pyplot").close(figure)

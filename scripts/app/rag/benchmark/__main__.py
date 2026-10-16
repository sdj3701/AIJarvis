# 파이썬 공부 | scripts/app/rag/benchmark/__main__.py
# 문서 검색 성능 평가를 명령줄에서 실행하는 시작점입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""CLI entry point for ``python -m app.rag.benchmark``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from app.config.defaults import DEFAULT_CONFIG_DIR
from app.config.loader import load_config
from app.core.errors import JarvisError
from app.core.ids import SystemIdFactory
from app.memory.migrations import initialize_database
from app.rag.benchmark.datasets import load_evaluation_queries
from app.rag.benchmark.retrievers import FTS5_NAME, RRF_NAME, VECTOR_NAME
from app.rag.benchmark.runner import BenchmarkRunner, BenchmarkRunResult
from app.rag.indexer import DocumentIndexer


# _parser(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: argparse.ArgumentParser.
def _parser() -> argparse.ArgumentParser:
    # argparse.ArgumentParser()의 반환값을 parser에 대입합니다.
    parser = argparse.ArgumentParser(description="Jarvis 로컬 RAG 검색 성능 번치마크")
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument("--dataset", type=Path, default=Path("datasets/evaluation_queries.json"))
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/evaluations"))
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument(
        "--top-k",
        type=int,
        nargs="+",
        choices=(1, 3, 5, 10),
        default=(1, 3, 5, 10),
        help="모든 검색 방식에 공통 적용할 top-k 값들 (default: 1 3 5 10)",
    )
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument("--repeats", type=int, default=5, help="쿼리당 실제 측정 횟수 (default: 5)")
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument(
        "--warmup-queries",
        type=int,
        default=10,
        help="방식별 워밍업 쿼리 수 (default: 10)",
    )
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument(
        "--sync",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="측정 전 현재 docs_dir를 기존 DocumentIndexer로 동기화 (default: disabled)",
    )
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument("--limit", type=int, help="확인용으로 앞에서부터 N개 쿼리만 실행")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return parser


# main(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: argv.
# 반환 타입 힌트: 정수(int).
def main(argv: list[str] | None = None) -> int:
    # _parser()의 반환값을 parser에 대입합니다.
    parser = _parser()
    # parser.parse_args()의 반환값을 args에 대입합니다.
    args = parser.parse_args(argv)
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: args.repeats <= 0.
        if args.repeats <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("--repeats는 1 이상이어야 합니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: args.warmup_queries < 0.
        if args.warmup_queries < 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("--warmup-queries는 0 이상이어야 합니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: args.limit is not None and args.limit
        # <= 0.
        if args.limit is not None and args.limit <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("--limit은 1 이상이어야 합니다.")

        # load_config()의 반환값을 loaded에 대입합니다.
        loaded = load_config(args.config_dir)
        # _data_path()의 반환값을 database_path에 대입합니다.
        database_path = _data_path(loaded.settings.paths.data_root, loaded.settings.paths.memory_db)
        # initialize_database()을 호출해 작업을 수행합니다.
        initialize_database(database_path)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: args.sync.
        if args.sync:
            # _data_path()의 반환값을 docs_root에 대입합니다.
            docs_root = _data_path(loaded.settings.paths.data_root, loaded.settings.paths.docs_dir)
            # 아래 함수()의 반환값을 report에 대입합니다.
            report = DocumentIndexer(
                database_path=database_path,
                docs_root=docs_root,
                settings=loaded.settings.rag,
                document_policy=loaded.policies.privacy.api_transmission.documents,
                ids=SystemIdFactory(),
            ).sync()
            # 값을 텍스트로 출력합니다.
            print(
                f"문서 동기화: 새로 인덱싱 {report.indexed}, 업데이트 {report.updated}, "
                f"삭제 {report.removed}, 건너뛰 {report.skipped}"
            )
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: report.errors.
            if report.errors:
                # 값을 텍스트로 출력합니다.
                print("동기화 경고:")
                # for 반복문: 대상의 항목을 하나씩 error에 대입하며 아래 블록을 실행합니다.
                for error in report.errors:
                    # 값을 텍스트로 출력합니다.
                    print(f"  - {error}")

        # load_evaluation_queries()의 반환값을 queries에 대입합니다.
        queries = load_evaluation_queries(args.dataset)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: args.limit is not None.
        if args.limit is not None:
            # 오른쪽 식을 계산한 값을 queries에 대입합니다.
            # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
            queries = queries[: args.limit]
        # 아래 함수()의 반환값을 result에 대입합니다.
        result = BenchmarkRunner(
            database_path=database_path,
            evaluation_queries=queries,
            output_dir=args.output_dir,
            rrf_k=loaded.settings.rag.rrf_k,
            top_k_values=args.top_k,
            repeats=args.repeats,
            warmup_queries=args.warmup_queries,
        ).run()
        # _print_console_report()을 호출해 작업을 수행합니다.
        _print_console_report(result, reporting_top_k=max(args.top_k))
        # 0을 반환하고 이 함수의 실행을 끝냅니다.
        return 0
    # (JarvisError, OSError, RuntimeError, ValueError)를 잡아 처리합니다. as 뒤의 이름에는 발생한
    # 예외 객체가 담깁니다.
    except (JarvisError, OSError, RuntimeError, ValueError) as error:
        # 값을 텍스트로 출력합니다.
        print(f"번치마크 실행 실패: {error}", file=sys.stderr)
        # 2을 반환하고 이 함수의 실행을 끝냅니다.
        return 2


# _data_path(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: data_root, configured.
# 반환 타입 힌트: Path.
def _data_path(data_root: Path, configured: Path) -> Path:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: configured.is_absolute().
    if configured.is_absolute():
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return configured.resolve(strict=False)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return (data_root / configured).resolve(strict=False)


# _print_console_report(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: result, reporting_top_k.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def _print_console_report(result: BenchmarkRunResult, *, reporting_top_k: int) -> None:
    # 오른쪽 식을 계산한 값을 rows에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    rows = [row for row in result.summary_rows if int(row["top_k"]) == reporting_top_k]
    # 값을 텍스트로 출력합니다.
    print(f"\n=== Local RAG Benchmark (top_k={reporting_top_k}) ===")
    # for 반복문: 대상의 항목을 하나씩 method에 대입하며 아래 블록을 실행합니다.
    for method in (VECTOR_NAME, FTS5_NAME, RRF_NAME):
        # _row()의 반환값을 row에 대입합니다.
        row = _row(rows, method)
        # 값을 텍스트로 출력합니다.
        print(
            f"{method}: Recall@5={float(row['recall_at_5']):.3f}, "
            f"MRR@10={float(row['mrr_at_10']):.3f}, nDCG@10={float(row['ndcg_at_10']):.3f}"
        )
        # 값을 텍스트로 출력합니다.
        print(
            f"  검색 지연시간(ms): 평균={float(row['latency_avg_ms']):.2f}, "
            f"P50={float(row['latency_p50_ms']):.2f}, P95={float(row['latency_p95_ms']):.2f}; "
            f"전체 응답={float(row['total_response_avg_ms']):.2f}"
        )

    # 값을 텍스트로 출력합니다.
    print("\n쿼리 유형별 Recall@5 최고 성능:")
    # 오른쪽 식을 계산한 값을 selected_types에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    selected_types = [row for row in result.query_type_rows if int(row["top_k"]) == reporting_top_k]
    # for 반복문: 대상의 항목을 하나씩 query_type에 대입하며 아래 블록을 실행합니다.
    for query_type in ("keyword", "semantic", "hybrid"):
        # 오른쪽 식을 계산한 값을 candidates에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        candidates = [row for row in selected_types if row["query_type"] == query_type]
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: candidates.
        if candidates:
            # max()의 반환값을 winner에 대입합니다.
            winner = max(
                candidates,
                key=lambda row: (float(row["recall_at_5"]), -float(row["latency_avg_ms"])),
            )
            # 값을 텍스트로 출력합니다.
            print(
                f"  {query_type}: {winner['retriever']} "
                f"(Recall@5={float(winner['recall_at_5']):.3f})"
            )

    # _recommended_method()의 반환값을 recommendation에 대입합니다.
    recommendation = _recommended_method(rows)
    # 값을 텍스트로 출력합니다.
    print(
        "\n종합 추천: "
        f"{recommendation['retriever']} "
        "(Recall@5·50% + MRR@10·25% + nDCG@10·25%, 속도 동점 해소)"
    )
    # 값을 텍스트로 출력합니다.
    print("\n결과 파일:")
    # for 반복문: 대상의 항목을 하나씩 path에 대입하며 아래 블록을 실행합니다.
    for path in (
        result.summary_path,
        result.per_query_path,
        result.by_query_type_path,
        result.report_path,
        result.catalog_path,
        *result.chart_paths,
    ):
        # 값을 텍스트로 출력합니다.
        print(f"  {path}")


# _row(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: rows, retriever.
# 반환 타입 힌트: dict[str, Any].
def _row(rows: list[dict[str, Any]], retriever: str) -> dict[str, Any]:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return next(row for row in rows if row["retriever"] == retriever)


# _recommended_method(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: rows.
# 반환 타입 힌트: dict[str, Any].
def _recommended_method(rows: list[dict[str, Any]]) -> dict[str, Any]:
    # min()의 반환값을 min_latency에 대입합니다.
    min_latency = min(float(row["latency_avg_ms"]) for row in rows)

    # score(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: row.
    # 반환 타입 힌트: tuple[float, float].
    def score(row: dict[str, Any]) -> tuple[float, float]:
        # 오른쪽 식을 계산한 값을 quality에 대입합니다.
        quality = (
            0.50 * float(row["recall_at_5"])
            + 0.25 * float(row["mrr_at_10"])
            + 0.25 * float(row["ndcg_at_10"])
        )
        # Quality decides the recommendation; lower search latency breaks close ties.
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return quality, min_latency / max(float(row["latency_avg_ms"]), 0.000001)

    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return max(rows, key=score)


# 이 파일을 실행 진입점으로 사용할 때만 아래 코드를 실행합니다. import할 때는 실행하지 않습니다.
if __name__ == "__main__":
    # SystemExit 예외로 프로그램 종료를 요청합니다. 전달한 값은 종료 상태를 나타냅니다.
    raise SystemExit(main())

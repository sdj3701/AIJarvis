# 파이썬 공부 | scripts/tests/unit/test_rag_benchmark_retrievers.py
# rag_benchmark_retrievers 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Contract tests for the isolated benchmark retrievers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.memory.migrations import initialize_database
from app.rag.benchmark.retrievers import (
    FTS5SearchRetriever,
    HybridRRFSearchRetriever,
    VectorSearchRetriever,
    load_indexed_chunks,
)
from tests.unit.test_semantic_memory import FakeEmbedder


# pytest가 test_benchmark_retrievers_return_a_common_result_contract()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_benchmark_retrievers_return_a_common_result_contract(tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 database_path에 대입합니다.
    database_path = tmp_path / "memory" / "jarvis.sqlite3"
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(database_path)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with sqlite3.connect(database_path) as connection:
        # connection.executemany()을 호출해 작업을 수행합니다.
        connection.executemany(
            """
            INSERT INTO documents(
                doc_id, path, content_hash, transfer_class, indexed_at, bytes, chunk_count
            )
            VALUES (?, ?, ?, 'local_only', '2026-01-01T00:00:00+00:00', ?, 1)
            """,
            (
                ("doc_reactor", "reactor.txt", "a" * 64, 40),
                ("doc_recipe", "recipe.txt", "b" * 64, 40),
            ),
        )
        # connection.executemany()을 호출해 작업을 수행합니다.
        connection.executemany(
            """
            INSERT INTO doc_chunks(chunk_id, doc_id, ordinal, text, start_char, end_char)
            VALUES (?, ?, 0, ?, 0, ?)
            """,
            (
                ("chunk_reactor", "doc_reactor", "아크 리액터 냉각수 과부하 경고", 18),
                ("chunk_recipe", "doc_recipe", "토마토 파스타 요리 레시피", 15),
            ),
        )

    # load_indexed_chunks()의 반환값을 chunks에 대입합니다.
    chunks = load_indexed_chunks(database_path)
    # 오른쪽 식을 계산한 값을 artifact_dir에 대입합니다.
    artifact_dir = tmp_path / "results" / "indexes"
    # FTS5SearchRetriever()의 반환값을 fts5에 대입합니다.
    fts5 = FTS5SearchRetriever(chunks, artifact_dir=artifact_dir)
    # VectorSearchRetriever()의 반환값을 vector에 대입합니다.
    vector = VectorSearchRetriever(chunks, artifact_dir=artifact_dir, embedder=FakeEmbedder())
    # HybridRRFSearchRetriever()의 반환값을 hybrid에 대입합니다.
    hybrid = HybridRRFSearchRetriever(vector, fts5, rrf_k=60)
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # for 반복문: 대상의 항목을 하나씩 retriever에 대입하며 아래 블록을 실행합니다.
        for retriever in (vector, fts5, hybrid):
            # retriever.search()의 반환값을 results에 대입합니다.
            results = retriever.search("아크 리액터 냉각수", top_k=2)
            # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
            assert results
            # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
            assert set(results[0]) == {"document_id", "chunk_id", "content", "score", "rank"}
            # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
            assert results[0]["rank"] == 1
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert vector.index_cost.artifact_path is not None
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert vector.index_cost.artifact_path.is_file()
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert fts5.index_cost.artifact_path is not None
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert fts5.index_cost.artifact_path.is_file()
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert hybrid.index_cost.size_mb == vector.index_cost.size_mb + fts5.index_cost.size_mb
    # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
    finally:
        # 사용하던 연결이나 자원을 닫습니다.
        fts5.close()

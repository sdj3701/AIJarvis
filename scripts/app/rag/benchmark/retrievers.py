# 파이썬 공부 | scripts/app/rag/benchmark/retrievers.py
# 벡터 검색, FTS5 전문 검색, RRF 순위 결합을 비교할 수 있게 구현합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Independent Vector, FTS5, and RRF retrievers used by the benchmark.

These retrievers read the existing ``documents`` and ``doc_chunks`` data but
write benchmark-only index artifacts.  They never alter the application's
production RAG tables or search behavior.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path
from time import perf_counter_ns
from typing import Protocol

from app.config.models import SemanticSettings
from app.rag.benchmark.models import IndexCost, IndexedChunk, RetrievalResult, SearchTrace
from app.rag.embeddings import reciprocal_rank_fusion
from app.rag.local_embedder import Embedder, LocalOllamaEmbedder, embed_query, retrieval_identity
from app.rag.semantic import SemanticMemory

# VECTOR_NAME에 문자열을 대입합니다.
VECTOR_NAME = "Vector Search"
# FTS5_NAME에 문자열을 대입합니다.
FTS5_NAME = "FTS5 Search"
# RRF_NAME에 문자열을 대입합니다.
RRF_NAME = "Hybrid RRF"


# BenchmarkRetriever: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class BenchmarkRetriever(Protocol):
    """Common public retrieval interface required by the benchmark."""

    # name: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    name: str

    # search(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: query, top_k.
    # 반환 타입 힌트: list[RetrievalResult].
    def search(self, query: str, top_k: int = 5) -> list[RetrievalResult]: ...

    # search_with_trace(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: query, top_k.
    # 반환 타입 힌트: SearchTrace.
    def search_with_trace(self, query: str, top_k: int = 5) -> SearchTrace: ...

    # index_cost(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: IndexCost.
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def index_cost(self) -> IndexCost: ...


# load_indexed_chunks(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: database_path.
# 반환 타입 힌트: tuple[IndexedChunk, ...].
def load_indexed_chunks(database_path: Path) -> tuple[IndexedChunk, ...]:
    """Read the canonical chunks already managed by ``DocumentIndexer``."""

    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not database_path.is_file().
    if not database_path.is_file():
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError(f"검색 DB가 없습니다: {database_path}")
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with sqlite3.connect(database_path) as connection:
        # 아래 함수()의 반환값을 rows에 대입합니다.
        rows = connection.execute(
            """
            SELECT dc.doc_id, dc.chunk_id, dc.text, d.path
            FROM doc_chunks AS dc
            JOIN documents AS d ON d.doc_id = dc.doc_id
            ORDER BY dc.doc_id, dc.ordinal, dc.chunk_id
            """
        ).fetchall()
    # tuple()의 반환값을 chunks에 대입합니다.
    chunks = tuple(
        IndexedChunk(
            document_id=str(row[0]),
            chunk_id=str(row[1]),
            content=str(row[2]),
            source_path=str(row[3]),
        )
        for row in rows
    )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not chunks.
    if not chunks:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError(
            "인덱싱된 문서 청크가 없습니다. --sync로 문서를 먼저 인덱싱하거나 "
            "docs_dir을 확인하세요."
        )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return chunks


# VectorSearchRetriever: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class VectorSearchRetriever:
    """Learned local embeddings and persistent sqlite-vec cosine search."""

    name = VECTOR_NAME

    def __init__(
        self,
        chunks: Sequence[IndexedChunk],
        *,
        artifact_dir: Path,
        embedder: Embedder | None = None,
    ) -> None:
        _validate_chunks(chunks)
        self._artifact_path = artifact_dir / "vector_index.sqlite3"
        self._engine = embedder or LocalOllamaEmbedder()
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}
        self._store = SemanticMemory(self._artifact_path, SemanticSettings(), embedder=self._engine)
        started = perf_counter_ns()
        self._store.sync_documents(
            [
                {
                    "chunk_id": c.chunk_id,
                    "doc_id": c.document_id,
                    "text": c.content,
                    "source_path": c.source_path,
                }
                for c in chunks
            ]
        )
        if self._store.last_error:
            raise RuntimeError("Benchmark requires local embeddings: " + self._store.last_error)
        self._index_cost = IndexCost(
            build_ms=_elapsed_ms(started),
            size_mb=_file_size_mb(self._artifact_path),
            process_memory_mb=_process_memory_mb(),
            artifact_path=self._artifact_path,
        )

    @property
    def index_cost(self) -> IndexCost:
        return self._index_cost

    def search(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        return list(self.search_with_trace(query, top_k=top_k).results)

    def search_with_trace(self, query: str, top_k: int = 5) -> SearchTrace:
        _validate_top_k(top_k)
        if not query.strip():
            return SearchTrace((), 0.0, 0.0, 0.0)
        started = perf_counter_ns()
        vector = embed_query(self._engine, query)
        embedding_ms = _elapsed_ms(started)
        started = perf_counter_ns()
        ranked = self._store.search_document_vector(
            vector, model=retrieval_identity(self._engine), limit=top_k
        )
        results = tuple(
            _result(self._chunks[key], score=score, rank=rank)
            for rank, (key, score) in enumerate(ranked, start=1)
        )
        search_ms = _elapsed_ms(started)
        return SearchTrace(results, embedding_ms, search_ms, embedding_ms + search_ms)


# FTS5SearchRetriever: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FTS5SearchRetriever:
    """SQLite FTS5 BM25 search against a benchmark-only FTS index."""

    # 오른쪽 식을 계산한 값을 name에 대입합니다.
    name = FTS5_NAME

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: chunks, artifact_dir.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, chunks: Sequence[IndexedChunk], *, artifact_dir: Path) -> None:
        # _validate_chunks()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_chunks(chunks)
        # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
        artifact_dir.mkdir(parents=True, exist_ok=True)
        # 오른쪽 식을 계산한 값을 self._artifact_path에 대입합니다.
        self._artifact_path = artifact_dir / "fts5_index.sqlite3"

        # perf_counter_ns()의 반환값을 started에 대입합니다.
        started = perf_counter_ns()
        # _recreate_fts5_index()을 호출해 작업을 수행합니다.
        _recreate_fts5_index(self._artifact_path, chunks)
        # _elapsed_ms()의 반환값을 build_ms에 대입합니다.
        build_ms = _elapsed_ms(started)
        # sqlite3.connect()의 반환값을 self._connection에 대입합니다.
        self._connection = sqlite3.connect(self._artifact_path)
        # 오른쪽 식을 계산한 값을 self._connection.row_factory에 대입합니다.
        self._connection.row_factory = sqlite3.Row
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        self._connection.execute("PRAGMA query_only = ON")
        # IndexCost()의 반환값을 self._index_cost에 대입합니다.
        self._index_cost = IndexCost(
            build_ms=build_ms,
            size_mb=_sqlite_artifact_size_mb(self._artifact_path),
            process_memory_mb=_process_memory_mb(),
            artifact_path=self._artifact_path,
        )

    # index_cost(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: IndexCost.
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def index_cost(self) -> IndexCost:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._index_cost

    # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def close(self) -> None:
        # 사용하던 연결이나 자원을 닫습니다.
        self._connection.close()

    # search(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: query, top_k.
    # 반환 타입 힌트: list[RetrievalResult].
    def search(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return list(self.search_with_trace(query, top_k=top_k).results)

    # search_with_trace(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: query, top_k.
    # 반환 타입 힌트: SearchTrace.
    def search_with_trace(self, query: str, top_k: int = 5) -> SearchTrace:
        # _validate_top_k()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_top_k(top_k)
        # _fts_match_query()의 반환값을 fts_query에 대입합니다.
        fts_query = _fts_match_query(query)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not fts_query.
        if not fts_query:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return SearchTrace((), 0.0, 0.0, 0.0)
        # perf_counter_ns()의 반환값을 search_started에 대입합니다.
        search_started = perf_counter_ns()
        # 아래 함수()의 반환값을 rows에 대입합니다.
        rows = self._connection.execute(
            """
            SELECT document_id, chunk_id, content, bm25(benchmark_chunks_fts) AS bm25_score
            FROM benchmark_chunks_fts
            WHERE benchmark_chunks_fts MATCH ?
            ORDER BY bm25_score, chunk_id
            LIMIT ?
            """,
            (fts_query, top_k),
        ).fetchall()
        # _elapsed_ms()의 반환값을 search_ms에 대입합니다.
        search_ms = _elapsed_ms(search_started)
        # tuple()의 반환값을 results에 대입합니다.
        results = tuple(_fts_result(row, rank=rank) for rank, row in enumerate(rows, start=1))
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return SearchTrace(
            results=results,
            embedding_ms=0.0,
            search_ms=search_ms,
            total_response_ms=search_ms,
        )


# HybridRRFSearchRetriever: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class HybridRRFSearchRetriever:
    """Fuse the Vector and FTS5 rankings with Reciprocal Rank Fusion."""

    # 오른쪽 식을 계산한 값을 name에 대입합니다.
    name = RRF_NAME

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: vector, fts5, rrf_k, candidate_multiplier.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        vector: VectorSearchRetriever,
        fts5: FTS5SearchRetriever,
        *,
        rrf_k: int = 60,
        candidate_multiplier: int = 5,
    ) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: rrf_k <= 0.
        if rrf_k <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("rrf_k는 0보다 크게 설정해야 합니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: candidate_multiplier <= 0.
        if candidate_multiplier <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("candidate_multiplier는 0보다 크게 설정해야 합니다.")
        # 오른쪽 식을 계산한 값을 self._vector에 대입합니다.
        self._vector = vector
        # 오른쪽 식을 계산한 값을 self._fts5에 대입합니다.
        self._fts5 = fts5
        # 오른쪽 식을 계산한 값을 self._rrf_k에 대입합니다.
        self._rrf_k = rrf_k
        # 오른쪽 식을 계산한 값을 self._candidate_multiplier에 대입합니다.
        self._candidate_multiplier = candidate_multiplier
        # 오른쪽 식을 계산한 값을 vector_cost에 대입합니다.
        vector_cost = vector.index_cost
        # 오른쪽 식을 계산한 값을 fts_cost에 대입합니다.
        fts_cost = fts5.index_cost
        # IndexCost()의 반환값을 self._index_cost에 대입합니다.
        self._index_cost = IndexCost(
            build_ms=vector_cost.build_ms + fts_cost.build_ms,
            size_mb=vector_cost.size_mb + fts_cost.size_mb,
            process_memory_mb=_process_memory_mb(),
            artifact_path=None,
        )

    # index_cost(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: IndexCost.
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def index_cost(self) -> IndexCost:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._index_cost

    # search(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: query, top_k.
    # 반환 타입 힌트: list[RetrievalResult].
    def search(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return list(self.search_with_trace(query, top_k=top_k).results)

    # search_with_trace(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: query, top_k.
    # 반환 타입 힌트: SearchTrace.
    def search_with_trace(self, query: str, top_k: int = 5) -> SearchTrace:
        # _validate_top_k()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_top_k(top_k)
        # max()의 반환값을 candidate_k에 대입합니다.
        candidate_k = max(top_k, top_k * self._candidate_multiplier)
        # self._vector.search_with_trace()의 반환값을 vector_trace에 대입합니다.
        vector_trace = self._vector.search_with_trace(query, top_k=candidate_k)
        # self._fts5.search_with_trace()의 반환값을 fts5_trace에 대입합니다.
        fts5_trace = self._fts5.search_with_trace(query, top_k=candidate_k)

        # perf_counter_ns()의 반환값을 fusion_started에 대입합니다.
        fusion_started = perf_counter_ns()
        # 오른쪽 식을 계산한 값을 vector_ids에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        vector_ids = [result["chunk_id"] for result in vector_trace.results]
        # 오른쪽 식을 계산한 값을 fts5_ids에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        fts5_ids = [result["chunk_id"] for result in fts5_trace.results]
        # 오른쪽 식을 계산한 값을 rankings에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        rankings = [ranking for ranking in (vector_ids, fts5_ids) if ranking]
        # 오른쪽 식을 계산한 값을 fused에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        fused = reciprocal_rank_fusion(rankings, k=self._rrf_k) if rankings else []
        # 오른쪽 식을 계산한 값을 result_by_chunk_id에 대입합니다.
        # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
        result_by_chunk_id = {
            result["chunk_id"]: result for result in (*vector_trace.results, *fts5_trace.results)
        }
        # results에 리스트(순서가 있고 수정 가능)을 대입합니다.
        results: list[RetrievalResult] = []
        # for 반복문: 대상의 항목을 하나씩 (rank, (chunk_id, score))에 대입하며 아래 블록을
        # 실행합니다.
        for rank, (chunk_id, score) in enumerate(fused[:top_k], start=1):
            # 오른쪽 식을 계산한 값을 source에 대입합니다.
            source = result_by_chunk_id[chunk_id]
            # 리스트 끝에 항목 하나를 추가합니다.
            results.append(
                {
                    "document_id": source["document_id"],
                    "chunk_id": chunk_id,
                    "content": source["content"],
                    "score": score,
                    "rank": rank,
                }
            )
        # _elapsed_ms()의 반환값을 fusion_ms에 대입합니다.
        fusion_ms = _elapsed_ms(fusion_started)
        # 오른쪽 식을 계산한 값을 search_ms에 대입합니다.
        search_ms = vector_trace.search_ms + fts5_trace.search_ms + fusion_ms
        # 오른쪽 식을 계산한 값을 total_response_ms에 대입합니다.
        total_response_ms = vector_trace.embedding_ms + search_ms
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return SearchTrace(
            results=tuple(results),
            embedding_ms=vector_trace.embedding_ms,
            search_ms=search_ms,
            total_response_ms=total_response_ms,
        )


# _recreate_fts5_index(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, chunks.
# 반환 타입 힌트: 별도 결과 없음(None).
def _recreate_fts5_index(path: Path, chunks: Sequence[IndexedChunk]) -> None:
    # for 반복문: 대상의 항목을 하나씩 candidate에 대입하며 아래 블록을 실행합니다.
    for candidate in _sqlite_artifact_paths(path):
        # 지정한 파일 또는 링크를 삭제합니다.
        candidate.unlink(missing_ok=True)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with sqlite3.connect(path) as connection:
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute(
            """
            CREATE VIRTUAL TABLE benchmark_chunks_fts
            USING fts5(document_id UNINDEXED, chunk_id UNINDEXED, content, tokenize='trigram')
            """
        )
        # connection.executemany()을 호출해 작업을 수행합니다.
        connection.executemany(
            """
            INSERT INTO benchmark_chunks_fts(document_id, chunk_id, content)
            VALUES (?, ?, ?)
            """,
            [(chunk.document_id, chunk.chunk_id, chunk.content) for chunk in chunks],
        )
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute(
            "INSERT INTO benchmark_chunks_fts(benchmark_chunks_fts) VALUES('optimize')"
        )
        # 데이터베이스 변경 내용을 확정합니다.
        connection.commit()
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")


# _fts_match_query(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: query.
# 반환 타입 힌트: 문자열(str).
def _fts_match_query(query: str) -> str:
    # 오른쪽 식을 계산한 값을 tokens에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    tokens = [token.replace('"', "") for token in query.split() if token.strip()]
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return " OR ".join(f'"{token}"' for token in tokens if token)


# _result(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: chunk, score, rank.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: RetrievalResult.
def _result(chunk: IndexedChunk, *, score: float, rank: int) -> RetrievalResult:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return {
        "document_id": chunk.document_id,
        "chunk_id": chunk.chunk_id,
        "content": chunk.content,
        "score": float(score),
        "rank": rank,
    }


# _fts_result(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: row, rank.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: RetrievalResult.
def _fts_result(row: sqlite3.Row, *, rank: int) -> RetrievalResult:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return {
        "document_id": str(row["document_id"]),
        "chunk_id": str(row["chunk_id"]),
        "content": str(row["content"]),
        # FTS5 BM25 returns a lower-is-better value; normalize to higher-is-better.
        "score": -float(row["bm25_score"]),
        "rank": rank,
    }


# _elapsed_ms(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: started_ns.
# 반환 타입 힌트: 실수(float).
def _elapsed_ms(started_ns: int) -> float:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return (perf_counter_ns() - started_ns) / 1_000_000


# _validate_top_k(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: top_k.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_top_k(top_k: int) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: top_k <= 0.
    if top_k <= 0:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("top_k는 0보다 크게 설정해야 합니다.")


# _validate_chunks(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: chunks.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_chunks(chunks: Sequence[IndexedChunk]) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not chunks.
    if not chunks:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("인덱싱할 문서 청크가 없습니다.")


# _file_size_mb(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: 실수(float).
def _file_size_mb(path: Path) -> float:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return path.stat().st_size / (1024 * 1024)


# _sqlite_artifact_paths(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: tuple[Path, ...].
def _sqlite_artifact_paths(path: Path) -> tuple[Path, ...]:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return (path, path.with_name(f"{path.name}-wal"), path.with_name(f"{path.name}-shm"))


# _sqlite_artifact_size_mb(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: 실수(float).
def _sqlite_artifact_size_mb(path: Path) -> float:
    # sum()의 반환값을 size에 대입합니다.
    size = sum(
        candidate.stat().st_size for candidate in _sqlite_artifact_paths(path) if candidate.exists()
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return size / (1024 * 1024)


# _process_memory_mb(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: float | None.
def _process_memory_mb() -> float | None:
    """Return RSS when psutil is installed; benchmarking still works without it."""

    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # import_module()의 반환값을 psutil에 대입합니다.
        psutil = import_module("psutil")
    # ImportError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except ImportError:
        # None을 반환하고 이 함수의 실행을 끝냅니다.
        return None
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return float(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024))

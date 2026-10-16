# 파이썬 공부 | scripts/app/rag/embeddings.py
# 텍스트를 숫자 벡터로 표현하고 벡터 사이의 유사도를 계산합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Local Dense Vector Embedding and Cosine Similarity Engine.

Provides 100% offline mathematical vectorization, L2 normalization,
Cosine Similarity metrics, and fast Top-K dense retrieval without external APIs.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

# DEFAULT_VECTOR_DIM에 숫자 등 고정된 값을 대입합니다.
DEFAULT_VECTOR_DIM: Final[int] = 512


# dot_product(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: vec_a, vec_b.
# 반환 타입 힌트: 실수(float).
def dot_product(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Calculate the algebraic dot product (내적) between two vectors."""
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(vec_a) != len(vec_b).
    if len(vec_a) != len(vec_b):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError(f"Vector dimension mismatch: {len(vec_a)} != {len(vec_b)}")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return sum(a * b for a, b in zip(vec_a, vec_b))


# l2_norm(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: vec.
# 반환 타입 힌트: 실수(float).
def l2_norm(vec: Sequence[float]) -> float:
    """Calculate Euclidean (L2) norm of a vector: sqrt(sum(x_i^2))."""
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return math.sqrt(sum(x * x for x in vec))


# l2_normalize(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: vec.
# 반환 타입 힌트: list[float].
def l2_normalize(vec: Sequence[float]) -> list[float]:
    """Normalize vector to unit length (L2 norm = 1.0)."""
    # l2_norm()의 반환값을 norm에 대입합니다.
    norm = l2_norm(vec)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: norm < 1e-12.
    if norm < 1e-12:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return [0.0] * len(vec)
    # 오른쪽 식을 계산한 값을 inv에 대입합니다.
    inv = 1.0 / norm
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    return [x * inv for x in vec]


# cosine_similarity(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: vec_a, vec_b.
# 반환 타입 힌트: 실수(float).
def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Calculate Cosine Similarity between two vectors in range [-1.0, 1.0].

    Formula:
        cos(theta) = (A · B) / (||A||_2 * ||B||_2)
    """
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(vec_a) != len(vec_b).
    if len(vec_a) != len(vec_b):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError(f"Vector dimension mismatch: {len(vec_a)} != {len(vec_b)}")
    # l2_norm()의 반환값을 norm_a에 대입합니다.
    norm_a = l2_norm(vec_a)
    # l2_norm()의 반환값을 norm_b에 대입합니다.
    norm_b = l2_norm(vec_b)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: norm_a < 1e-12 or norm_b < 1e-12.
    if norm_a < 1e-12 or norm_b < 1e-12:
        # 0.0을 반환하고 이 함수의 실행을 끝냅니다.
        return 0.0
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return dot_product(vec_a, vec_b) / (norm_a * norm_b)


# VectorDocument: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class VectorDocument:
    """Document chunk container with text and vector."""
    # doc_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    doc_id: str
    # chunk_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    chunk_id: str
    # text: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    text: str
    # vector에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    vector: tuple[float, ...] = ()


# VectorSearchResult: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    """Ranked search hit with similarity score."""
    # doc_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    doc_id: str
    # chunk_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    chunk_id: str
    # text: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    text: str
    # score: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    score: float  # Cosine similarity in range [-1.0, 1.0]


# LocalEmbeddingEngine: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class LocalEmbeddingEngine:
    """Pure-Python Multi-scale Feature Hashing Semantic Vectorizer (100% Offline).

    Converts arbitrary multi-lingual text into a normalized continuous vector space
    using word roots, multi-scale n-grams (1, 2, 3-char), and L2 unit hypersphere projection.
    """

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: dimension.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, dimension: int = DEFAULT_VECTOR_DIM) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: dimension <= 0.
        if dimension <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("Vector dimension must be a positive integer")
        # 오른쪽 식을 계산한 값을 self._dim에 대입합니다.
        self._dim = dimension

    # dimension(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 정수(int).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def dimension(self) -> int:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._dim

    # embed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text.
    # 반환 타입 힌트: list[float].
    def embed(self, text: str) -> list[float]:
        """Convert input text into a normalized D-dimensional float vector."""
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not text or not text.strip().
        if not text or not text.strip():
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return [0.0] * self._dim

        # 오른쪽 식을 계산한 값을 vec에 대입합니다.
        vec = [0.0] * self._dim
        # text.lower().strip()의 반환값을 clean_text에 대입합니다.
        clean_text = text.lower().strip()

        # 1. Word Tokens
        # re.findall()의 반환값을 words에 대입합니다.
        words = re.findall(r"[a-zA-Z0-9가-힣]+", clean_text)
        # for 반복문: 대상의 항목을 하나씩 word에 대입하며 아래 블록을 실행합니다.
        for word in words:
            # Word-level bucket
            # 오른쪽 식을 계산한 값을 w_idx에 대입합니다.
            w_idx = int(hashlib.md5(word.encode("utf-8")).hexdigest()[:8], 16) % self._dim
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            vec[w_idx] += 2.0 + math.log1p(len(word))

        # 2. Multi-scale character n-grams (2-gram and 3-gram for Korean root matching)
        # re.sub()의 반환값을 text_no_space에 대입합니다.
        text_no_space = re.sub(r"\s+", "", clean_text)
        # len()의 반환값을 text_len에 대입합니다.
        text_len = len(text_no_space)
        # for 반복문: 대상의 항목을 하나씩 n에 대입하며 아래 블록을 실행합니다.
        for n in (2, 3):
            # for 반복문: 대상의 항목을 하나씩 i에 대입하며 아래 블록을 실행합니다.
            for i in range(text_len - n + 1):
                # 오른쪽 식을 계산한 값을 ngram에 대입합니다.
                # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
                ngram = text_no_space[i : i + n]
                # 오른쪽 식을 계산한 값을 ng_idx에 대입합니다.
                ng_idx = int(hashlib.sha256(ngram.encode("utf-8")).hexdigest()[:8], 16) % self._dim
                # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                vec[ng_idx] += 1.0

        # 3. L2 Normalization
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return l2_normalize(vec)


# VectorStore: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class VectorStore:
    """In-memory & SQLite Vector Store for Dense Retrieval."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: engine.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, engine: LocalEmbeddingEngine | None = None) -> None:
        # 오른쪽 식을 계산한 값을 self._engine에 대입합니다.
        self._engine = engine or LocalEmbeddingEngine()
        # self._docs에 딕셔너리(키와 값의 쌍)을 대입합니다.
        self._docs: dict[str, VectorDocument] = {}

    # add(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: doc.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def add(self, doc: VectorDocument) -> None:
        """Add a document chunk, automatically generating its vector if missing."""
        # 오른쪽 식을 계산한 값을 vec에 대입합니다.
        vec = doc.vector or tuple(self._engine.embed(doc.text))
        # VectorDocument()의 반환값을 self._docs[doc.chunk_id]에 대입합니다.
        self._docs[doc.chunk_id] = VectorDocument(
            doc_id=doc.doc_id,
            chunk_id=doc.chunk_id,
            text=doc.text,
            vector=vec,
        )

    # search(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: query, top_k.
    # 반환 타입 힌트: list[VectorSearchResult].
    def search(self, query: str, top_k: int = 5) -> list[VectorSearchResult]:
        """Search top-K most semantically relevant document chunks using Cosine Similarity."""
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not query.strip() or not self._docs.
        if not query.strip() or not self._docs:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return []

        # self._engine.embed()의 반환값을 query_vec에 대입합니다.
        query_vec = self._engine.embed(query)
        # scored에 리스트(순서가 있고 수정 가능)을 대입합니다.
        scored: list[tuple[VectorDocument, float]] = []

        # for 반복문: 대상의 항목을 하나씩 doc에 대입하며 아래 블록을 실행합니다.
        for doc in self._docs.values():
            # cosine_similarity()의 반환값을 sim에 대입합니다.
            sim = cosine_similarity(query_vec, doc.vector)
            # 리스트 끝에 항목 하나를 추가합니다.
            scored.append((doc, sim))

        # Sort by similarity descending (highest cosine score first)
        # scored.sort()을 호출해 작업을 수행합니다.
        scored.sort(key=lambda item: item[1], reverse=True)

        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        return [
            VectorSearchResult(
                doc_id=doc.doc_id,
                chunk_id=doc.chunk_id,
                text=doc.text,
                score=score,
            )
            for doc, score in scored[:top_k]
        ]


# reciprocal_rank_fusion(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: rankings, k.
# 반환 타입 힌트: list[tuple[str, float]].
def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Combine multiple ranking lists into a unified score using RRF algorithm.

    Formula:
        RRF_Score(d) = sum_{m in models} (1.0 / (k + rank_m(d)))

    Args:
        rankings: A sequence of ranked item ID lists from different retrieval engines.
        k: Smoothing constant to dampen high-rank advantages (standard constant = 60).

    Returns:
        Sorted list of (item_id, rrf_score) tuples in descending order of score.
    """
    # scores에 딕셔너리(키와 값의 쌍)을 대입합니다.
    scores: dict[str, float] = {}
    # for 반복문: 대상의 항목을 하나씩 rank_list에 대입하며 아래 블록을 실행합니다.
    for rank_list in rankings:
        # for 반복문: 대상의 항목을 하나씩 (rank_idx, item_id)에 대입하며 아래 블록을 실행합니다.
        for rank_idx, item_id in enumerate(rank_list, start=1):
            # 오른쪽 식을 계산한 값을 scores[item_id]에 대입합니다.
            scores[item_id] = scores.get(item_id, 0.0) + (1.0 / (k + rank_idx))

    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)

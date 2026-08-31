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

DEFAULT_VECTOR_DIM: Final[int] = 512


def dot_product(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Calculate the algebraic dot product (내적) between two vectors."""
    if len(vec_a) != len(vec_b):
        raise ValueError(f"Vector dimension mismatch: {len(vec_a)} != {len(vec_b)}")
    return sum(a * b for a, b in zip(vec_a, vec_b))


def l2_norm(vec: Sequence[float]) -> float:
    """Calculate Euclidean (L2) norm of a vector: sqrt(sum(x_i^2))."""
    return math.sqrt(sum(x * x for x in vec))


def l2_normalize(vec: Sequence[float]) -> list[float]:
    """Normalize vector to unit length (L2 norm = 1.0)."""
    norm = l2_norm(vec)
    if norm < 1e-12:
        return [0.0] * len(vec)
    inv = 1.0 / norm
    return [x * inv for x in vec]


def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Calculate Cosine Similarity between two vectors in range [-1.0, 1.0].
    
    Formula:
        cos(theta) = (A · B) / (||A||_2 * ||B||_2)
    """
    if len(vec_a) != len(vec_b):
        raise ValueError(f"Vector dimension mismatch: {len(vec_a)} != {len(vec_b)}")
    norm_a = l2_norm(vec_a)
    norm_b = l2_norm(vec_b)
    if norm_a < 1e-12 or norm_b < 1e-12:
        return 0.0
    return dot_product(vec_a, vec_b) / (norm_a * norm_b)


@dataclass(frozen=True, slots=True)
class VectorDocument:
    """Document chunk container with text and vector."""
    doc_id: str
    chunk_id: str
    text: str
    vector: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    """Ranked search hit with similarity score."""
    doc_id: str
    chunk_id: str
    text: str
    score: float  # Cosine similarity in range [-1.0, 1.0]


class LocalEmbeddingEngine:
    """Pure-Python Multi-scale Feature Hashing Semantic Vectorizer (100% Offline).
    
    Converts arbitrary multi-lingual text into a normalized continuous vector space
    using word roots, multi-scale n-grams (1, 2, 3-char), and L2 unit hypersphere projection.
    """

    def __init__(self, dimension: int = DEFAULT_VECTOR_DIM) -> None:
        if dimension <= 0:
            raise ValueError("Vector dimension must be a positive integer")
        self._dim = dimension

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        """Convert input text into a normalized D-dimensional float vector."""
        if not text or not text.strip():
            return [0.0] * self._dim

        vec = [0.0] * self._dim
        clean_text = text.lower().strip()

        # 1. Word Tokens
        words = re.findall(r"[a-zA-Z0-9가-힣]+", clean_text)
        for word in words:
            # Word-level bucket
            w_idx = int(hashlib.md5(word.encode("utf-8")).hexdigest()[:8], 16) % self._dim
            vec[w_idx] += 2.0 + math.log1p(len(word))

        # 2. Multi-scale character n-grams (2-gram and 3-gram for Korean root matching)
        text_no_space = re.sub(r"\s+", "", clean_text)
        text_len = len(text_no_space)
        for n in (2, 3):
            for i in range(text_len - n + 1):
                ngram = text_no_space[i : i + n]
                ng_idx = int(hashlib.sha256(ngram.encode("utf-8")).hexdigest()[:8], 16) % self._dim
                vec[ng_idx] += 1.0

        # 3. L2 Normalization
        return l2_normalize(vec)


class VectorStore:
    """In-memory & SQLite Vector Store for Dense Retrieval."""

    def __init__(self, engine: LocalEmbeddingEngine | None = None) -> None:
        self._engine = engine or LocalEmbeddingEngine()
        self._docs: dict[str, VectorDocument] = {}

    def add(self, doc: VectorDocument) -> None:
        """Add a document chunk, automatically generating its vector if missing."""
        vec = doc.vector or tuple(self._engine.embed(doc.text))
        self._docs[doc.chunk_id] = VectorDocument(
            doc_id=doc.doc_id,
            chunk_id=doc.chunk_id,
            text=doc.text,
            vector=vec,
        )

    def search(self, query: str, top_k: int = 5) -> list[VectorSearchResult]:
        """Search top-K most semantically relevant document chunks using Cosine Similarity."""
        if not query.strip() or not self._docs:
            return []

        query_vec = self._engine.embed(query)
        scored: list[tuple[VectorDocument, float]] = []

        for doc in self._docs.values():
            sim = cosine_similarity(query_vec, doc.vector)
            scored.append((doc, sim))

        # Sort by similarity descending (highest cosine score first)
        scored.sort(key=lambda item: item[1], reverse=True)

        return [
            VectorSearchResult(
                doc_id=doc.doc_id,
                chunk_id=doc.chunk_id,
                text=doc.text,
                score=score,
            )
            for doc, score in scored[:top_k]
        ]

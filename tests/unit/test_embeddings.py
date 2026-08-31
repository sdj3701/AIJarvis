from __future__ import annotations

import math
import pytest
from app.rag.embeddings import (
    cosine_similarity,
    l2_normalize,
    dot_product,
    LocalEmbeddingEngine,
    VectorStore,
    VectorDocument,
)


def test_dot_product_and_l2_normalize() -> None:
    vec = [3.0, 4.0]
    norm = l2_normalize(vec)
    assert pytest.approx(math.sqrt(norm[0] ** 2 + norm[1] ** 2), 1e-6) == 1.0
    assert pytest.approx(norm[0], 1e-6) == 0.6
    assert pytest.approx(norm[1], 1e-6) == 0.8


def test_cosine_similarity_identical_and_orthogonal() -> None:
    vec_a = [1.0, 2.0, 3.0]
    vec_b = [1.0, 2.0, 3.0]
    # Identical vectors should have similarity 1.0
    assert pytest.approx(cosine_similarity(vec_a, vec_b), 1e-6) == 1.0

    # Orthogonal vectors should have similarity 0.0
    vec_x = [1.0, 0.0]
    vec_y = [0.0, 1.0]
    assert pytest.approx(cosine_similarity(vec_x, vec_y), 1e-6) == 0.0

    # Opposite vectors should have similarity -1.0
    vec_neg = [-1.0, -2.0, -3.0]
    assert pytest.approx(cosine_similarity(vec_a, vec_neg), 1e-6) == -1.0


def test_local_embedding_engine_semantic_similarity() -> None:
    engine = LocalEmbeddingEngine(dimension=512)
    
    # Meaningfully similar sentences sharing concepts (pizza, preference, food)
    emb1 = engine.embed("보스는 맛있는 피자와 파스타를 좋아합니다.")
    emb2 = engine.embed("보스의 선호 음식은 피자와 스파게티입니다.")
    emb_diff = engine.embed("주식 시장에서 비트코인 암호화폐 거래량이 폭증했다.")

    sim_similar = cosine_similarity(emb1, emb2)
    sim_different = cosine_similarity(emb1, emb_diff)

    assert len(emb1) == 512
    # Similar food topics must score significantly higher than unrelated crypto topic
    assert sim_similar > sim_different
    assert sim_similar > 0.20


def test_vector_store_top_k_ranking() -> None:
    engine = LocalEmbeddingEngine(dimension=128)
    store = VectorStore(engine=engine)

    store.add(VectorDocument(doc_id="doc_1", chunk_id="chk_1", text="파이썬 RAG 시스템 아키텍처 설계와 구현"))
    store.add(VectorDocument(doc_id="doc_2", chunk_id="chk_2", text="스타크 인더스트리 아크 리액터 HUD 디자인"))
    store.add(VectorDocument(doc_id="doc_3", chunk_id="chk_3", text="오늘의 점심 메뉴 추천 및 맛집 지도"))

    results = store.search("파이썬 코딩과 RAG 검색 엔진", top_k=2)
    assert len(results) == 2
    assert results[0].chunk_id == "chk_1"  # doc_1 should be 1st rank
    assert results[0].score > results[1].score

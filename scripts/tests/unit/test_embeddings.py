# 파이썬 공부 | scripts/tests/unit/test_embeddings.py
# embeddings 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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


# pytest가 test_dot_product_and_l2_normalize()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_dot_product_and_l2_normalize() -> None:
    # vec에 리스트(순서가 있고 수정 가능)을 대입합니다.
    vec = [3.0, 4.0]
    # l2_normalize()의 반환값을 norm에 대입합니다.
    norm = l2_normalize(vec)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert pytest.approx(math.sqrt(norm[0] ** 2 + norm[1] ** 2), 1e-6) == 1.0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert pytest.approx(norm[0], 1e-6) == 0.6
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert pytest.approx(norm[1], 1e-6) == 0.8


# pytest가 test_cosine_similarity_identical_and_orthogonal()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_cosine_similarity_identical_and_orthogonal() -> None:
    # vec_a에 리스트(순서가 있고 수정 가능)을 대입합니다.
    vec_a = [1.0, 2.0, 3.0]
    # vec_b에 리스트(순서가 있고 수정 가능)을 대입합니다.
    vec_b = [1.0, 2.0, 3.0]
    # Identical vectors should have similarity 1.0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert pytest.approx(cosine_similarity(vec_a, vec_b), 1e-6) == 1.0

    # Orthogonal vectors should have similarity 0.0
    # vec_x에 리스트(순서가 있고 수정 가능)을 대입합니다.
    vec_x = [1.0, 0.0]
    # vec_y에 리스트(순서가 있고 수정 가능)을 대입합니다.
    vec_y = [0.0, 1.0]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert pytest.approx(cosine_similarity(vec_x, vec_y), 1e-6) == 0.0

    # Opposite vectors should have similarity -1.0
    # vec_neg에 리스트(순서가 있고 수정 가능)을 대입합니다.
    vec_neg = [-1.0, -2.0, -3.0]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert pytest.approx(cosine_similarity(vec_a, vec_neg), 1e-6) == -1.0


# pytest가 test_local_embedding_engine_semantic_similarity()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_local_embedding_engine_semantic_similarity() -> None:
    # LocalEmbeddingEngine()의 반환값을 engine에 대입합니다.
    engine = LocalEmbeddingEngine(dimension=512)

    # Meaningfully similar sentences sharing concepts (pizza, preference, food)
    # engine.embed()의 반환값을 emb1에 대입합니다.
    emb1 = engine.embed("보스는 맛있는 피자와 파스타를 좋아합니다.")
    # engine.embed()의 반환값을 emb2에 대입합니다.
    emb2 = engine.embed("보스의 선호 음식은 피자와 스파게티입니다.")
    # engine.embed()의 반환값을 emb_diff에 대입합니다.
    emb_diff = engine.embed("주식 시장에서 비트코인 암호화폐 거래량이 폭증했다.")

    # cosine_similarity()의 반환값을 sim_similar에 대입합니다.
    sim_similar = cosine_similarity(emb1, emb2)
    # cosine_similarity()의 반환값을 sim_different에 대입합니다.
    sim_different = cosine_similarity(emb1, emb_diff)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(emb1) == 512
    # Similar food topics must score significantly higher than unrelated crypto topic
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert sim_similar > sim_different
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert sim_similar > 0.20


# pytest가 test_vector_store_top_k_ranking()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_vector_store_top_k_ranking() -> None:
    # LocalEmbeddingEngine()의 반환값을 engine에 대입합니다.
    engine = LocalEmbeddingEngine(dimension=128)
    # VectorStore()의 반환값을 store에 대입합니다.
    store = VectorStore(engine=engine)

    # add 메서드를 호출해 항목이나 기록을 추가합니다.
    store.add(VectorDocument(doc_id="doc_1", chunk_id="chk_1", text="파이썬 RAG 시스템 아키텍처 설계와 구현"))
    # add 메서드를 호출해 항목이나 기록을 추가합니다.
    store.add(VectorDocument(doc_id="doc_2", chunk_id="chk_2", text="스타크 인더스트리 아크 리액터 HUD 디자인"))
    # add 메서드를 호출해 항목이나 기록을 추가합니다.
    store.add(VectorDocument(doc_id="doc_3", chunk_id="chk_3", text="오늘의 점심 메뉴 추천 및 맛집 지도"))

    # store.search()의 반환값을 results에 대입합니다.
    results = store.search("파이썬 코딩과 RAG 검색 엔진", top_k=2)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(results) == 2
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert results[0].chunk_id == "chk_1"  # doc_1 should be 1st rank
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert results[0].score > results[1].score


# pytest가 test_reciprocal_rank_fusion()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_reciprocal_rank_fusion() -> None:
    from app.rag.embeddings import reciprocal_rank_fusion

    # Engine A (FTS): doc_1 is 1st, doc_2 is 2nd
    # Engine B (Vector): doc_2 is 1st, doc_1 is 2nd, doc_3 is 3rd
    # fts_ranks에 리스트(순서가 있고 수정 가능)을 대입합니다.
    fts_ranks = ["doc_1", "doc_2"]
    # vec_ranks에 리스트(순서가 있고 수정 가능)을 대입합니다.
    vec_ranks = ["doc_2", "doc_1", "doc_3"]

    # reciprocal_rank_fusion()의 반환값을 fused에 대입합니다.
    fused = reciprocal_rank_fusion([fts_ranks, vec_ranks], k=60)
    # doc_1: 1/(60+1) + 1/(60+2) = 1/61 + 1/62 = 0.016393 + 0.016129 = 0.032522
    # doc_2: 1/(60+2) + 1/(60+1) = 0.032522
    # doc_3: 1/(60+3) = 0.015873
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(fused) == 3
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert fused[2][0] == "doc_3"  # doc_3 should be lowest
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert fused[0][1] > fused[2][1]

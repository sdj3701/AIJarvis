"""Opt-in real Korean ranking tests using installed local models; writes only to tmp_path."""

from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import pytest

from app.config.defaults import DEFAULT_DATA_ROOT
from app.config.loader import load_config
from app.config.models import RerankSettings, SemanticSettings
from app.core.ids import SystemIdFactory
from app.memory.migrations import initialize_database
from app.rag.indexer import DocumentIndexer
from app.rag.reranker import Candidate, Reranker
from app.rag.semantic import SemanticMemory

pytestmark = [pytest.mark.phase3, pytest.mark.allow_network]
MODELS_ROOT = DEFAULT_DATA_ROOT / "models"


def test_real_korean_cross_encoder_and_deadline() -> None:
    ranker = Reranker(RerankSettings(), MODELS_ROOT)
    candidates = [
        Candidate("food", "토마토 파스타는 면을 삶아 소스와 버무립니다.", .04),
        Candidate("office", "회사 사무실은 3층에 있습니다.", .03),
        Candidate("leave", "연차 휴가는 사용하기 사흘 전에 인사 포털에서 신청합니다.", .02),
    ]
    query = "회사에서 쉬려면 언제 신청해야 하나요?"
    for _ in range(2):
        start = perf_counter()
        hits = ranker.rank(query, candidates)
        print({"elapsed_ms": round((perf_counter() - start) * 1000),
               "order": [c.key for c in hits], "scores": [c.rerank_score for c in hits]})
        assert ranker.last_error is None
        assert hits[0].key == "leave"
        assert hits[0].score == .02
    # Deadline failure must discard the entire rerank, not return a partial batch.
    ranker = Reranker(RerankSettings(timeout_s=1e-9), MODELS_ROOT)
    assert ranker.rank(query, candidates) == candidates
    assert ranker.last_error == "TimeoutError"


def test_real_hybrid_conversation_reranking(tmp_path: Path) -> None:
    ranker = Reranker(RerankSettings(), MODELS_ROOT)
    store = SemanticMemory(tmp_path / "semantic.sqlite3", SemanticSettings(), reranker=ranker)
    now = datetime.now(UTC)
    for turn, question, answer in [
        ("food", "내가 좋아하는 음식은?", "토마토 파스타입니다."),
        ("leave", "연차 휴가는 어떻게 신청해?", "사용하기 사흘 전에 인사 포털에서 신청합니다."),
        ("office", "회사 사무실 위치는?", "사무실은 3층입니다."),
    ]:
        store.remember_turn(session_id="smoke", turn_id=turn, question=question,
                            answer=answer, created_at=now)
    hits = store.recall("회사 휴가를 신청하는 방법은?", now=now, limit=1)
    assert store.last_error is None
    assert ranker.status == "ready"
    assert hits[0]["turn_id"] == "leave"
    assert hits[0]["rerank_score"] is not None
    assert hits[0]["verified"] is False


def test_real_hybrid_document_reranking(config_dir: Path) -> None:
    loaded = load_config(config_dir)
    root = loaded.settings.paths.data_root
    docs = root / "docs"
    docs.mkdir()
    for name, text in {
        "leave.txt": "연차 휴가는 사용하기 사흘 전에 인사 포털에서 신청합니다.",
        "food.txt": "토마토 파스타는 면을 삶아 소스와 버무립니다.",
        "office.txt": "회사 사무실은 3층에 있습니다.",
    }.items():
        (docs / name).write_text(text, encoding="utf-8")
    db = root / "memory" / "jarvis.sqlite3"
    initialize_database(db)
    ranker = Reranker(RerankSettings(), MODELS_ROOT)
    settings = loaded.settings.rag.model_copy(update={
        "semantic": SemanticSettings(min_similarity=-1),
    })
    indexer = DocumentIndexer(db, docs, settings,
                              loaded.policies.privacy.api_transmission.documents,
                              SystemIdFactory(), reranker=ranker)
    assert indexer.sync().errors == ()
    hits = indexer.search("회사에서 쉬려면 언제 신청해야 하나요?", max_chunks=1)
    assert ranker.status == "ready"
    assert len(hits) == 1
    assert hits[0].relative_path == "leave.txt"
    assert hits[0].rerank_score is not None

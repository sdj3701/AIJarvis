"""Second-stage ranking must improve selection without losing the RRF fallback."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.config.models import RerankSettings, SemanticSettings
from app.rag.reranker import Candidate, Reranker, verify_model_files
from app.rag.semantic import SemanticMemory
from tests.unit.test_hybrid_search import hybrid_indexer  # noqa: F401

pytestmark = pytest.mark.phase3


class Scorer:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.passages: list[str] = []

    def score(self, query: str, passages: list[str]) -> list[float]:
        self.passages = passages
        return self.scores


def test_rerank_before_top_k_preserves_rrf_scores(tmp_path: Path) -> None:
    scorer = Scorer([-4.0, 8.0, 8.0])
    ranker = Reranker(RerankSettings(), tmp_path, scorer=scorer)
    candidates = [Candidate(str(i), f"passage {i}", 1 / (60 + i)) for i in range(3)]
    result = ranker.rank("query", candidates)
    assert [r.key for r in result] == ["1", "2", "0"]
    assert result[0].score == candidates[1].score
    assert result[0].rerank_score == 8.0


@pytest.mark.parametrize("scores", [[1.0], [float("nan"), 2.0], [float("inf"), 1.0]])
def test_invalid_output_keeps_complete_rrf_order(tmp_path: Path, scores: list[float]) -> None:
    ranker = Reranker(RerankSettings(), tmp_path, scorer=Scorer(scores))
    candidates = [Candidate("a", "a", 0.03), Candidate("b", "b", 0.02)]
    assert ranker.rank("q", candidates) == candidates
    assert ranker.last_error == "ValueError"


def test_disabled_and_missing_model_fall_back(tmp_path: Path) -> None:
    candidates = [Candidate("a", "a", 1), Candidate("b", "b", 0)]
    scorer = Scorer([1, 2])
    ranker = Reranker(RerankSettings(enabled=False), tmp_path, scorer=scorer)
    assert ranker.rank("q", candidates) == candidates
    assert scorer.passages == []
    ranker = Reranker(RerankSettings(), tmp_path)
    assert ranker.rank("q", candidates) == candidates
    assert ranker.last_error == "FileNotFoundError"


def test_candidate_cap_leaves_tail(tmp_path: Path) -> None:
    scorer = Scorer([1.0, 2.0])
    ranker = Reranker(RerankSettings(candidate_count=2), tmp_path, scorer=scorer)
    candidates = [Candidate(str(i), str(i), 1 / (60 + i)) for i in range(4)]
    assert [r.key for r in ranker.rank("q", candidates)] == ["1", "0", "2", "3"]
    assert len(scorer.passages) == 2


def test_conversation_candidates_are_reranked_before_limit(tmp_path: Path) -> None:
    now = datetime(2026, 10, 13, tzinfo=UTC)
    scorer = Scorer([0.0, 10.0])
    ranker = Reranker(RerankSettings(), tmp_path, scorer=scorer)
    memory = SemanticMemory(tmp_path / "memory.db", SemanticSettings(enabled=False),
                            reranker=ranker)
    for turn, answer in [("a", "휴가 알림"), ("b", "휴가 신청은 인사 포털에서 합니다.")]:
        memory.remember_turn(session_id="s", turn_id=turn, question="휴가",
                             answer=answer, created_at=now)
    result = memory.recall("휴가", now=now, limit=1)
    assert len(scorer.passages) == 2  # unique pairs, not duplicate question/answer hits
    assert result[0]["turn_id"] == "b"
    assert result[0]["answer"] == "휴가 신청은 인사 포털에서 합니다."
    assert result[0]["rerank_score"] == 10.0
    assert result[0]["verified"] is False
    assert memory.recall("휴가", now=now, exclude_turn_id="b")[0]["turn_id"] == "a"


def test_document_rerank_precedes_selection(hybrid_indexer, tmp_path: Path) -> None:  # noqa: F811
    object.__setattr__(hybrid_indexer, "reranker",
                       Reranker(RerankSettings(enabled=False), tmp_path))
    hybrid_indexer.sync()
    baseline = hybrid_indexer.search("ERR_STARK_007 파스타", max_chunks=2)
    assert len(baseline) == 2
    ranker = Reranker(RerankSettings(), tmp_path, scorer=Scorer([-3.0, 9.0]))
    object.__setattr__(hybrid_indexer, "reranker", ranker)
    hybrid_indexer.sync()
    hits = hybrid_indexer.search("ERR_STARK_007 파스타", max_chunks=1)
    assert hits[0].relative_path == baseline[1].relative_path
    assert hits[0].rerank_score == 9.0


def test_failure_has_cooldown_and_recovers(tmp_path: Path) -> None:
    class FailingScorer:
        calls = 0

        def score(self, query: str, passages: list[str]) -> list[float]:
            self.calls += 1
            raise TimeoutError("secret query should not appear in events")

    scorer = FailingScorer()
    ranker = Reranker(RerankSettings(), tmp_path, scorer=scorer)
    candidates = [Candidate("a", "a", 2), Candidate("b", "b", 1)]
    for _ in range(2):
        assert ranker.rank("query", candidates) == candidates
    assert scorer.calls == 1
    assert ranker.status == "rrf_fallback"
    ranker._retry_at = 0
    ranker.scorer = Scorer([0, 1])
    assert ranker.rank("q", candidates)[0].key == "b"
    assert ranker.last_error is None
    assert ranker.status == "ready"


def test_long_conversation_passes_matching_answer_excerpt_to_reranker(tmp_path: Path) -> None:
    now = datetime(2026, 10, 13, tzinfo=UTC)
    scorer = Scorer([0, 1])
    memory = SemanticMemory(tmp_path / "memory.db", SemanticSettings(enabled=False),
                            reranker=Reranker(RerankSettings(), tmp_path, scorer=scorer))
    for turn, answer in [("a", "휴가 알림"),
                         ("b", "다른 설명입니다. " * 400 + "휴가 신청 마감은 사흘 전입니다.")]:
        memory.remember_turn(session_id="s", turn_id=turn, question="휴가",
                             answer=answer, created_at=now)
    hits = memory.recall("휴가", now=now)
    assert any("휴가 신청 마감은 사흘 전" in p for p in scorer.passages)
    selected = next(h for h in hits if h["turn_id"] == "b")
    assert "휴가 신청 마감은 사흘 전" in selected["matched_text"]
    assert len(selected["answer"]) > 3000  # original pair remains intact


def test_corrupted_model_is_rejected_before_loading(tmp_path: Path) -> None:
    (tmp_path / "onnx").mkdir()
    (tmp_path / "onnx/model_quint8_avx2.onnx").write_bytes(b"corrupted model")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_model_files(tmp_path)

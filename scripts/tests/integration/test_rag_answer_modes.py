import json

import pytest

from app.llm.fake import FakeLLMClient
from tests.integration.test_search_answer_format import _research_runtime
from tests.unit.test_semantic_memory import FakeEmbedder

pytestmark = pytest.mark.phase3


def setup(config_dir, llm):
    runtime, chat = _research_runtime(config_dir, llm)
    runtime.indexer.semantic.embedder = FakeEmbedder()
    runtime.indexer.sync()
    chat.start()
    return runtime, chat


@pytest.mark.parametrize("channel", ["text", "voice"])
def test_general_fallback_label_sources_and_memory(config_dir, channel):
    llm = FakeLLMClient().reply("RAG는 검색 자료를 활용해 답변을 생성하는 방식입니다.")
    runtime, chat = setup(config_dir, llm)
    outcome = chat.handle_turn("RAG 개념 설명해줘", channel=channel)
    assert outcome.answer_mode == "general"
    assert not outcome.sources
    assert outcome.grounding_status is None
    assert "문서 근거 없는 일반 답변" in outcome.display_text
    assert "문서 근거 없는 일반 답변" in outcome.presentation.speech_text
    with runtime.indexer.semantic.connection() as db:
        metadata = json.loads(db.execute("SELECT metadata FROM conversation_turns").fetchone()[0])
    assert metadata["answer_mode"] == "general"
    assert metadata["verified"] is False


@pytest.mark.parametrize("query", ["출장 식비 한도는?", "내 계약 기간은?", "대표자 이름은?"])
def test_internal_or_unknown_scope_without_evidence_abstains(config_dir, query):
    llm = FakeLLMClient()
    _, chat = setup(config_dir, llm)
    result = chat.handle_turn(query)
    assert result.answer_mode == "abstained"
    assert not llm.calls
    assert not result.sources


def test_embedding_outage_is_not_general_knowledge_success(config_dir):
    llm = FakeLLMClient()
    runtime, chat = setup(config_dir, llm)
    (runtime.indexer.docs_root / "unrelated.md").write_text(
        "점심 식당은 정오에 문을 엽니다.", encoding="utf-8"
    )
    assert not runtime.indexer.sync().errors
    runtime.indexer.semantic.embedder.offline = True
    result = chat.handle_turn("RAG 원리는?")
    assert result.answer_mode == "abstained"
    assert result.fallback_reason == "retrieval_degraded"
    assert not llm.calls


def test_no_result_followup_retains_user_topic(config_dir):
    _, chat = setup(config_dir, FakeLLMClient())
    chat.handle_turn("우리 회사 연차 규정 알려줘")
    result = chat.handle_turn("그럼 며칠 전에 신청해?")
    assert result.answer_mode == "abstained"
    assert not result.intent_confirmation


def test_changed_source_during_model_outage_is_not_answered_as_current(config_dir):
    llm = FakeLLMClient()
    runtime, chat = setup(config_dir, llm)
    p = runtime.indexer.docs_root / "leave.md"
    p.write_text("연차는 3일 전에 신청합니다.", encoding="utf-8")
    runtime.indexer.sync()
    p.write_text("연차는 7일 전에 신청합니다.", encoding="utf-8")
    runtime.indexer.semantic.embedder.offline = True
    assert runtime.indexer.sync().errors
    result = chat.handle_turn("사내 연차 신청 기한은?")
    assert result.answer_mode == "abstained"
    assert result.fallback_reason == "retrieval_error"
    assert not llm.calls


def test_research_evidence_is_trimmed_to_generation_budget(config_dir, monkeypatch):
    from app.llm.ollama_client import OllamaClient

    llm = FakeLLMClient().reply('{"status":"insufficient","claims":[]}')
    runtime, chat = setup(config_dir, llm)
    counter = OllamaClient(runtime.config.settings.llm).count_tokens
    monkeypatch.setattr(llm, "count_tokens", counter)
    for number in range(6):
        (runtime.indexer.docs_root / f"policy{number}.md").write_text(
            f"연차 규정 {number}\n" + "사용자는 담당자에게 신청 내용을 확인합니다. " * 50,
            encoding="utf-8",
        )
    runtime.indexer.sync()
    result = chat.handle_turn("사내 연차 규정을 알려줘")
    assert result.answer_mode == "abstained"
    if llm.calls:
        assert counter(llm.calls[0]) <= runtime.config.settings.llm.context.max_input_tokens
        prompt = "\n".join(m.content for m in llm.calls[0])
        assert prompt.count('source_id="S') < 6
    else:
        assert result.fallback_reason == "context_budget"

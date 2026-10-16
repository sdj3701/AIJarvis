import json
from pathlib import Path

import pytest

from app.llm.fake import FakeLLMClient
from tests.integration.test_search_answer_format import _research_runtime

pytestmark = pytest.mark.phase3


def test_bad_passage_id_is_repaired_once_and_usage_is_accounted(config_dir: Path):
    from decimal import Decimal

    from app.llm.base import LLMUsage
    from app.rag.passages import make_passages

    statement = "연차는 3일 전에 신청합니다."

    def draft(identifier):
        return json.dumps(
            {
                "status": "answered",
                "claims": [
                    {
                        "text": statement,
                        "citations": [{"source_id": "S1", "passage_id": identifier}],
                    }
                ],
            }
        )

    llm = (
        FakeLLMClient()
        .reply(draft("S1.wrong"), usage=LLMUsage(10, 20, Decimal(0), 1))
        .reply(draft(make_passages(statement, "S1")[0].id), usage=LLMUsage(30, 40, Decimal(0), 2))
        .reply('{"supported":[true],"answers_question":true,"conflict":false}')
    )
    runtime, chat = _research_runtime(config_dir, llm)
    runtime.indexer.docs_root.mkdir(parents=True, exist_ok=True)
    (runtime.indexer.docs_root / "leave.md").write_text(statement, encoding="utf-8")
    runtime.indexer.sync()
    chat.start()
    result = chat.handle_turn("/search 연차")
    assert result.ok and result.grounding_status == "근거 확인"
    assert "S1.wrong" not in result.text
    assert len(llm.calls) == 3
    assert result.input_tokens == 40 and result.output_tokens == 60


def test_local_question_checks_claim_and_never_calls_web(config_dir: Path) -> None:
    statement = "연차는 3일 전에 신청합니다."
    draft = json.dumps(
        {
            "status": "answered",
            "claims": [
                {
                    "text": statement,
                    "citations": [
                        {"source_id": "S1", "quote": statement},
                    ],
                }
            ],
        },
        ensure_ascii=False,
    )
    llm = (
        FakeLLMClient()
        .reply(draft)
        .reply('{"supported":[true],"answers_question":true,"conflict":false}')
    )
    runtime, chat = _research_runtime(config_dir, llm)
    docs = runtime.indexer.docs_root
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "leave.md").write_text("연차신청 규정\n" + statement, encoding="utf-8")
    runtime.indexer.sync()
    provider = runtime.tool_runner.registry.tools["web_search"].provider
    chat.start()
    outcome = chat.handle_turn("우리 회사 연차신청 기한은?")
    assert outcome.ok
    assert outcome.grounding_status == "근거 확인"
    assert len(llm.calls) == 2
    assert provider.calls == []
    assert outcome.sources[0].startswith("leave.md#chunk=")
    assert "3일" in outcome.display_text
    assert "근거 확인" in outcome.text


def test_failed_claim_check_does_not_expose_or_remember_claim(config_dir: Path) -> None:
    statement = "연차는 3일 전에 신청합니다."
    llm = (
        FakeLLMClient()
        .reply(
            json.dumps(
                {
                    "status": "answered",
                    "claims": [
                        {
                            "text": "연차는 3일 전에 신청하지 않아도 됩니다.",
                            "citations": [{"source_id": "S1", "quote": statement}],
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )
        .reply('{"supported":[false],"answers_question":true,"conflict":false}')
        .reply('{"status":"insufficient","claims":[]}')
    )
    runtime, chat = _research_runtime(config_dir, llm)
    runtime.indexer.docs_root.mkdir(parents=True, exist_ok=True)
    (runtime.indexer.docs_root / "leave.md").write_text(
        "연차신청 규정\n" + statement,
        encoding="utf-8",
    )
    runtime.indexer.sync()
    chat.start()
    outcome = chat.handle_turn("우리 회사 연차신청 기한은?")
    assert outcome.grounding_status == "근거 부족"
    assert "신청하지 않아도" not in outcome.text
    assert "신청하지 않아도" not in chat._history[-1].content
    assert not outcome.sources
    assert "보류" in outcome.display_text
    assert len(llm.calls) == 3  # one bounded quote-selection repair, never exposed


def test_explicit_web_question_still_uses_web(config_dir: Path) -> None:
    llm = FakeLLMClient().reply('{"status":"insufficient","claims":[]}')
    runtime, chat = _research_runtime(config_dir, llm)
    chat.start()
    outcome = chat.handle_turn("/search 웹 Jarvis")
    assert outcome.grounding_status == "근거 부족"
    assert runtime.tool_runner.registry.tools["web_search"].provider.calls


def test_followup_retrieves_user_topic_and_preserves_original_question(config_dir: Path) -> None:
    from tests.unit.test_semantic_memory import FakeEmbedder

    statement = "출장 식비는 하루 30000원까지 지원합니다."
    draft = json.dumps(
        {
            "status": "answered",
            "claims": [
                {
                    "text": statement,
                    "citations": [
                        {"source_id": "S1", "quote": statement},
                    ],
                }
            ],
        },
        ensure_ascii=False,
    )
    llm = FakeLLMClient()
    for _ in range(2):
        llm.reply(draft).reply('{"supported":[true],"answers_question":true,"conflict":false}')
    runtime, chat = _research_runtime(config_dir, llm)
    runtime.indexer.semantic.embedder = FakeEmbedder()
    runtime.indexer.docs_root.mkdir(parents=True, exist_ok=True)
    (runtime.indexer.docs_root / "travel.md").write_text(statement, encoding="utf-8")
    runtime.indexer.sync()
    chat.start()
    first = chat.handle_turn("출장 식비 한도가 얼마야?")
    second = chat.handle_turn("그럼 하루에 얼마까지야?")
    assert first.grounding_status == second.grounding_status == "근거 확인"
    assert "출장 식비" in str(llm.calls[-2])
    assert chat._history[-2].content == "그럼 하루에 얼마까지야?"
    assert not runtime.tool_runner.registry.tools["web_search"].provider.calls

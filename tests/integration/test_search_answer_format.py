"""Integration tests for research answers with FakeSearchProvider."""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.llm.base import LLMUsage
from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.rag.search_provider import SearchFailed
from app.tools.impl.web_search import WebSearchTool
from app.tools.registry import spec_from_definition
from app.wiring import Runtime, build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock
from tests.fakes.search import FakeSearchProvider

pytestmark = pytest.mark.phase3
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


EVIDENCE_ANSWER = """\
핵심 요약
- Jarvis는 로컬 문서를 검색합니다 [1]

근거
[1] Example — https://example.com/jarvis (2026-08-11 확인)

상태: 근거 부족
"""


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    destination = tmp_path / "config"
    destination.mkdir()
    for name in ("settings", "tools", "privacy"):
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            destination / f"{name}.yaml",
        )
    root = tmp_path / "Jarvis"
    create_tree(root)
    settings_path = destination / "settings.yaml"
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    document["paths"]["data_root"] = str(root)
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return destination


def _research_runtime(config_dir: Path, llm: FakeLLMClient) -> tuple[Runtime, ChatOrchestrator]:
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=llm)
    initialize_database(runtime.memory_db, created_at=NOW)
    fake = FakeSearchProvider()
    fake.add_hit(
        title="Example",
        url="https://example.com/jarvis",
        snippet="Jarvis local docs",
        fetched_at=NOW,
    )
    enabled = {
        defn.name: spec_from_definition(defn)
        for defn in runtime.config.policies.tools.tools
        if defn.enabled and defn.name in {"web_search", "doc_search"}
    }
    runtime.tool_runner.registry.tools["web_search"] = WebSearchTool(
        spec=enabled["web_search"],
        provider=fake,
        gate=runtime.privacy_gate,
        budget=runtime.budget,
        default_max_results=runtime.config.settings.rag.search.max_results,
        cost_per_request=runtime.config.settings.rag.search.cost_per_request,
    )
    chat = ChatOrchestrator(
        settings=runtime.config.settings,
        llm=runtime.llm,
        sessions=runtime.sessions,
        budget=runtime.budget,
        masker=runtime.masker,
        events=runtime.events,
        clock=runtime.clock,
        sleeper=runtime.sleeper,
        random=runtime.random,
        ids=runtime.ids,
        metrics=runtime.metrics,
        summarizer=runtime.summarizer,
        indexer=runtime.indexer,
        research=runtime.research,
        tool_runner=runtime.tool_runner,
        safety_gate=runtime.safety_gate,
        approval_store=runtime.approval_store,
        audit_writer=runtime.audit_writer,
    )
    return runtime, chat


def test_unknown_fact_triggers_search_or_abstains(config_dir: Path) -> None:
    llm = FakeLLMClient().reply(EVIDENCE_ANSWER, usage=LLMUsage(10, 20, Decimal("0"), 5))
    _, chat = _research_runtime(config_dir, llm)
    chat.start()
    outcome = chat.handle_turn("/search Jarvis 문서 검색")
    assert outcome.ok is True
    assert any("untrusted_content" in message.content for call in llm.calls for message in call)


def test_answer_includes_url_and_status_label(config_dir: Path) -> None:
    llm = FakeLLMClient().reply(EVIDENCE_ANSWER)
    _, chat = _research_runtime(config_dir, llm)
    chat.start()
    outcome = chat.handle_turn("최신 Jarvis 검색해")
    assert re.search(r"https?://", outcome.text)
    assert re.search(r"상태\s*[:\uff1a]\s*(확실|상충|근거 부족)", outcome.text)


def test_duplicate_url_does_not_count_as_independent_source(config_dir: Path) -> None:
    llm = FakeLLMClient().reply("핵심 요약\n- 중복 결과 [1]\n\n상태: 확실")
    runtime, chat = _research_runtime(config_dir, llm)
    web_tool = runtime.tool_runner.registry.tools["web_search"]
    web_tool.provider.add_hit(  # type: ignore[attr-defined]
        title="Duplicate",
        url="https://example.com/jarvis#duplicate",
        snippet="같은 출처의 다른 검색 결과",
        fetched_at=NOW,
    )
    chat.start()

    outcome = chat.handle_turn("최신 Jarvis 검색해")

    assert "상태: 근거 부족" in outcome.text


def test_search_failure_is_reported_honestly(config_dir: Path) -> None:
    llm = FakeLLMClient().reply("should not be used")
    runtime, chat = _research_runtime(config_dir, llm)
    enabled = {
        defn.name: spec_from_definition(defn)
        for defn in runtime.config.policies.tools.tools
        if defn.enabled and defn.name == "web_search"
    }
    failing = FakeSearchProvider(fail_with=SearchFailed("검색 API 오류"))
    runtime.tool_runner.registry.tools["web_search"] = WebSearchTool(
        spec=enabled["web_search"],
        provider=failing,
        gate=runtime.privacy_gate,
        budget=runtime.budget,
        default_max_results=5,
        cost_per_request=Decimal("0"),
    )
    chat.start()
    outcome = chat.handle_turn("/search broken")
    assert outcome.ok is False
    assert "검색" in outcome.text
    assert llm.calls == []


def test_local_doc_answer_cites_filename(config_dir: Path, tmp_path: Path) -> None:
    llm = FakeLLMClient().reply(
        "핵심 요약\n- 로컬 문서 [1]\n\n근거\n"
        "[1] guide.md — docs (2026-08-11 확인)\n\n상태: 근거 부족"
    )
    runtime, chat = _research_runtime(config_dir, llm)
    docs = runtime.config.settings.paths.data_root / "docs" / "public"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "guide.md").write_text("Jarvis memory structure 설명", encoding="utf-8")
    runtime.indexer.sync(now=NOW)
    chat.start()
    outcome = chat.handle_turn("로컬 문서에서 memory structure 찾아줘")
    assert "guide.md" in outcome.text or "guide.md" in llm.calls[-1][1].content

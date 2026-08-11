"""Security tests for prompt injection corpus."""

from __future__ import annotations

import json
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
from app.tools.impl.web_search import WebSearchTool
from app.tools.registry import spec_from_definition
from app.wiring import build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock
from tests.fakes.search import FakeSearchProvider

pytestmark = [pytest.mark.phase3, pytest.mark.security]
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


def _load_cases() -> list[dict[str, str]]:
    path = REPOSITORY_ROOT / "tests" / "data" / "malicious" / "injection.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.fixture
def chat(tmp_path: Path) -> tuple[FakeLLMClient, ChatOrchestrator]:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in ("settings", "tools", "privacy"):
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            config_dir / f"{name}.yaml",
        )
    root = tmp_path / "Jarvis"
    create_tree(root)
    settings_path = config_dir / "settings.yaml"
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    document["paths"]["data_root"] = str(root)
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    llm = FakeLLMClient().reply(
        "핵심 요약\n- 요약 [1]\n\n근거\n[1] evil.md — local (2026-08-11 확인)\n\n상태: 근거 부족",
        usage=LLMUsage(1, 1, Decimal("0"), 1),
    )
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=llm)
    initialize_database(runtime.memory_db, created_at=NOW)
    fake = FakeSearchProvider()
    fake.add_hit(title="t", url="https://example.com", snippet="s", fetched_at=NOW)
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
        default_max_results=5,
        cost_per_request=Decimal("0"),
    )
    orchestrator = ChatOrchestrator(
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
        indexer=runtime.indexer,
        research=runtime.research,
        tool_runner=runtime.tool_runner,
        safety_gate=runtime.safety_gate,
        approval_store=runtime.approval_store,
        audit_writer=runtime.audit_writer,
    )
    return llm, orchestrator


@pytest.mark.parametrize("case", _load_cases(), ids=lambda item: item["id"])
def test_injection_corpus(
    chat: tuple[FakeLLMClient, ChatOrchestrator],
    case: dict[str, str],
) -> None:
    llm, orchestrator = chat
    docs = orchestrator._indexer.docs_root / "evil.md"
    docs.write_text(case["text"], encoding="utf-8")
    orchestrator._indexer.sync(now=NOW)
    orchestrator.start()
    orchestrator.handle_turn("/search evil")
    sent = "\n".join(message.content for call in llm.calls for message in call)
    assert "untrusted_content" in sent
    assert "create_file" not in sent.lower() or "데이터" in sent

"""Integration test for local document RAG."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.wiring import build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock

pytestmark = pytest.mark.phase3
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


def test_local_doc_answer_cites_filename(tmp_path: Path) -> None:
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
        "핵심 요약\n- Jarvis docs [1]\n\n근거\n"
        "[1] guide.md — docs/public/guide.md (2026-08-11 확인)\n\n"
        "상태: 근거 부족"
    )
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=llm)
    initialize_database(runtime.memory_db, created_at=NOW)
    public = runtime.indexer.docs_root / "public"
    public.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        REPOSITORY_ROOT / "tests" / "data" / "docs" / "public" / "guide.md",
        public / "guide.md",
    )
    runtime.indexer.sync(now=NOW)
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
        indexer=runtime.indexer,
        research=runtime.research,
        tool_runner=runtime.tool_runner,
        safety_gate=runtime.safety_gate,
        approval_store=runtime.approval_store,
        audit_writer=runtime.audit_writer,
    )
    chat.start()
    outcome = chat.handle_turn("로컬 guide.md에서 memory 검색해")
    assert "guide.md" in outcome.text

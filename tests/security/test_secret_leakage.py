"""Security tests for secret leakage and local_only documents."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from app.llm.fake import FakeLLMClient
from app.memory.commands import try_handle_memory_command
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.wiring import build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock
from tests.helpers.phase4_app import Phase4App

pytestmark = [pytest.mark.phase3, pytest.mark.security]
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)
SECRET = "sk-testAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def test_local_only_doc_not_sent_to_api(tmp_path: Path) -> None:
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
        "핵심 요약\n- 로컬 전용 [1]\n\n근거\n"
        "[1] private.txt — local (2026-08-11 확인)\n\n상태: 근거 부족"
    )
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=llm)
    initialize_database(runtime.memory_db, created_at=NOW)
    private = runtime.indexer.docs_root / "private"
    private.mkdir(parents=True, exist_ok=True)
    (private / "secret.txt").write_text(f"secret marker {SECRET}", encoding="utf-8")
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
        privacy_gate=runtime.privacy_gate,
    )
    chat.start()
    chat.handle_turn("/search secret")
    sent = "\n".join(message.content for call in llm.calls for message in call)
    assert SECRET not in sent
    assert "로컬 전용" in sent


def test_external_search_query_blocks_secret(tmp_path: Path) -> None:
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
    runtime = build(config_dir, clock=FrozenClock(NOW))
    decision = runtime.privacy_gate.for_external_text(
        f"query with {SECRET}",
        purpose="search_query",
    )
    assert decision.text is None
    assert decision.blocked is True


@pytest.mark.phase6
def test_secret_never_leaves(phase4_app: Phase4App) -> None:
    phase4_app.llm.reply("확인했습니다.")
    phase4_app.say(f"내 키는 {SECRET} 인데 기억해둬")

    sent = "\n".join(
        message.content for call in phase4_app.llm.calls for message in call
    )
    assert SECRET not in sent

    logs = phase4_app.data_root / "logs"
    for path in logs.rglob("*.jsonl"):
        assert SECRET not in path.read_text(encoding="utf-8")

    for record in phase4_app.runtime.sessions.list_records():
        assert SECRET not in record.value

    raw_dir = phase4_app.data_root / "memory" / "raw"
    for path in raw_dir.rglob("*.jsonl"):
        assert SECRET not in path.read_text(encoding="utf-8")

    spoken = phase4_app.runtime.privacy_gate.for_tts(f"키는 {SECRET} 입니다")
    assert SECRET not in spoken


@pytest.mark.phase6
def test_explicit_remember_blocks_secret(phase4_app: Phase4App) -> None:
    ctx = phase4_app.chat.memory_command_context()
    assert ctx is not None
    result = try_handle_memory_command(f"기억해: 말투 키는 {SECRET}", ctx)
    assert result is not None
    assert not result.ok
    assert all(
        SECRET not in record.value
        for record in phase4_app.runtime.sessions.list_records()
    )

"""Phase 2 integration tests for unfinished session recovery."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.memory.store import RawRecord
from app.orchestrator.recovery import recover_sessions
from app.wiring import build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock

pytestmark = pytest.mark.phase2
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


class RecordingEvents:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        self.items.append((event_type, dict(payload)))


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    destination = tmp_path / "config"
    destination.mkdir()
    for name in ("settings", "tools", "privacy"):
        source = REPOSITORY_ROOT / "config" / f"{name}.example.yaml"
        (destination / f"{name}.yaml").write_text(
            source.read_text(encoding="utf-8"),
            encoding="utf-8",
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


def _unfinished_runtime(config_dir: Path, *, recovery: str) -> tuple[Any, str]:
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=FakeLLMClient())
    initialize_database(runtime.memory_db, created_at=NOW)
    settings_path = config_dir / "settings.yaml"
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    document["session"]["recovery"] = recovery
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=FakeLLMClient())
    initialize_database(runtime.memory_db, created_at=NOW)
    session_id = runtime.ids.new("ses")
    runtime.sessions.start_session(session_id, NOW)
    runtime.sessions.append_raw(
        RawRecord(
            ts=NOW,
            session_id=session_id,
            turn_id=runtime.ids.new("turn"),
            role="user",
            content="미완료 세션",
            channel="text",
            request_id=runtime.ids.new("req"),
        )
    )
    return runtime, session_id


def test_discard_policy_ends_unfinished_session(config_dir: Path) -> None:
    runtime, session_id = _unfinished_runtime(config_dir, recovery="discard")
    events = RecordingEvents()

    report = recover_sessions(
        runtime.sessions,
        policy="discard",
        events=events,
        clock=runtime.clock,
    )

    session = runtime.sessions.get_session(session_id)
    assert session is not None and session.end_reason == "discarded"
    assert report.unfinished_count == 1
    assert any(item[1].get("action") == "discarded" for item in events.items)


def test_auto_policy_summarizes_unfinished_session(config_dir: Path) -> None:
    runtime, session_id = _unfinished_runtime(config_dir, recovery="auto")
    summary_json = json.dumps(
        {
            "schema_version": 1,
            "summary": "크래시 복구 요약",
            "fact_candidates": [],
            "corrections": [],
            "tags": [],
        },
        ensure_ascii=False,
    )
    runtime.llm.reply(summary_json)
    events = RecordingEvents()

    recover_sessions(
        runtime.sessions,
        policy="auto",
        events=events,
        clock=runtime.clock,
        summarizer=runtime.summarizer,
        settings=runtime.config.settings,
        ids=runtime.ids,
        sleeper=runtime.sleeper,
        random=runtime.random,
    )

    session = runtime.sessions.get_session(session_id)
    assert session is not None and session.end_reason == "crash_recovered"
    assert runtime.sessions.list_records(kind="summary")
    assert any(item[1].get("action") in {"summarized", "recovered"} for item in events.items)

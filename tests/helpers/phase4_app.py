"""Shared Phase 4 test application fixture."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.llm.base import LLMUsage
from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.telemetry.audit import read_audit_records
from app.wiring import Runtime, build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


@dataclass
class Phase4App:
    runtime: Runtime
    chat: ChatOrchestrator
    llm: FakeLLMClient
    data_root: Path

    def say(self, text: str) -> str:
        outcome = self.chat.handle_turn(text)
        if outcome.pending_approval is not None and outcome.pending_tool_call is not None:
            verdict = outcome.pending_approval
            ticket = self.runtime.approval_store.grant(
                verdict,
                ctx=self.chat.pending_context,  # type: ignore[arg-type]
                method="user_text",
            )
            resumed = self.chat.resume_after_approval(ticket)
            return resumed.text
        return outcome.text

    def audit(self) -> list[dict[str, Any]]:
        logs = self.data_root / "logs"
        return read_audit_records(logs)


def snapshot_tree(root: Path) -> dict[str, int]:
    excluded_prefixes = ("logs\\", "logs/", "memory\\raw", "memory/raw", "state\\", "state/")
    result: dict[str, int] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = str(path.relative_to(root)).replace("/", "\\")
        if any(relative.startswith(prefix) for prefix in excluded_prefixes):
            continue
        if "jarvis.sqlite3" in relative:
            continue
        result[relative] = path.stat().st_size
    return result


def build_phase4_app(config_dir: Path) -> Phase4App:
    settings_path = config_dir / "settings.yaml"
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    root = Path(document["paths"]["data_root"])
    create_tree(root)
    llm = FakeLLMClient().reply(
        "확인했습니다.",
        usage=LLMUsage(1, 1, Decimal("0"), 1),
    )
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=llm)
    initialize_database(runtime.memory_db, created_at=NOW)
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
        privacy_gate=runtime.privacy_gate,
    )
    chat.start()
    return Phase4App(runtime=runtime, chat=chat, llm=llm, data_root=root)


@pytest.fixture
def phase4_app(config_dir: Path) -> Phase4App:
    return build_phase4_app(config_dir)


def read_lines(name: str) -> list[str]:
    path = REPOSITORY_ROOT / "tests" / "data" / "paths" / name
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)
    return lines

"""Shared Phase 5 test application fixture with multi-step FakeLLM scripts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest
import yaml

from app.core.clock import Clock
from app.llm.base import LLMUsage
from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.orchestrator.recovery import recover_tasks
from app.wiring import Runtime, build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock
from tests.fakes.search import FakeSearchProvider

KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)
ApprovalMode = Literal["approve", "deny"]


@dataclass
class Phase5App:
    runtime: Runtime
    chat: ChatOrchestrator
    llm: FakeLLMClient
    search: FakeSearchProvider
    data_root: Path

    def handle(
        self,
        text: str,
        *,
        approval: ApprovalMode = "approve",
    ) -> str:
        outcome = self.chat.handle_turn(text)
        while outcome.pending_approval is not None and outcome.pending_tool_call is not None:
            if approval == "deny":
                self.chat.discard_pending_approval(cause="user_deny")
                return "작업을 실행하지 않았습니다."
            verdict = outcome.pending_approval
            ticket = self.runtime.approval_store.grant(
                verdict,
                ctx=self.chat.pending_context,  # type: ignore[arg-type]
                method=(
                    "user_typed_phrase"
                    if verdict.decision == "typed_confirm"
                    else "user_text"
                ),
            )
            outcome = self.chat.resume_after_approval(ticket)
        self._last_outcome = outcome
        return outcome.text

    @property
    def last_task_id(self) -> str | None:
        outcome = getattr(self, "_last_outcome", None)
        return None if outcome is None else outcome.task_id

    def recover_tasks(self) -> None:
        recover_tasks(self.runtime.task_store, self.runtime.events)


def build_phase5_app(
    config_dir: Path,
    *,
    llm: FakeLLMClient | None = None,
    max_steps: int | None = None,
    step_timeout_s: float | None = None,
    total_timeout_s: float | None = None,
    clock: Clock | None = None,
) -> Phase5App:
    settings_path = config_dir / "settings.yaml"
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    root = Path(document["paths"]["data_root"])
    create_tree(root)
    if max_steps is not None:
        document["agent"]["max_steps"] = max_steps
    if step_timeout_s is not None:
        document["agent"]["step_timeout_s"] = step_timeout_s
    if total_timeout_s is not None:
        document["agent"]["total_timeout_s"] = total_timeout_s
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    fake_llm = llm or FakeLLMClient().reply(
        "확인했습니다.",
        usage=LLMUsage(1, 1, Decimal("0"), 1),
    )
    runtime = build(config_dir, clock=clock or FrozenClock(NOW), llm=fake_llm)
    initialize_database(runtime.memory_db, created_at=NOW)
    search = FakeSearchProvider()
    search.add_hit(
        title="Jarvis 테스트",
        url="https://example.com/jarvis",
        snippet="Jarvis는 로컬 AI 비서입니다.",
        fetched_at=NOW,
    )
    web_tool = runtime.tool_runner.registry.tools.get("web_search")
    if web_tool is not None:
        web_tool.provider = search  # type: ignore[attr-defined]
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
        task_store=runtime.task_store,
    )
    chat.start()
    return Phase5App(
        runtime=runtime,
        chat=chat,
        llm=fake_llm,
        search=search,
        data_root=root,
    )


def golden_task_script(filename: str = "quantum-summary.md") -> FakeLLMClient:
    summary = (
        "핵심 요약: Jarvis는 로컬 AI 비서입니다 [1]. "
        "근거 [1] Jarvis 테스트 — https://example.com/jarvis (2026-08-11 확인). "
        "상태: 근거 부족"
    )
    return (
        FakeLLMClient()
        .call_tool("web_search", query="양자컴퓨팅")
        .call_tool(
            "create_file",
            root="notes",
            relative_path=filename,
            content=summary,
        )
        .call_tool("open_folder", root="notes", relative_path="")
        .reply(
            "검색·저장·폴더 열기를 완료했습니다.",
            usage=LLMUsage(10, 20, Decimal("0"), 1),
        )
    )


@pytest.fixture
def phase5_app(config_dir: Path) -> Phase5App:
    return build_phase5_app(config_dir)


def inject_create_file_script() -> FakeLLMClient:
    return (
        FakeLLMClient()
        .call_tool("web_search", query="양자컴퓨팅")
        .call_tool(
            "create_file",
            root="notes",
            relative_path="evil.md",
            content="injected",
        )
        .reply("done", usage=LLMUsage(1, 1, Decimal("0"), 1))
    )

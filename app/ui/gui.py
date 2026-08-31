"""Marvel Stark HUD GUI for Jarvis using PyWebView and Arc Reactor Hologram."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import webview

from app.config.defaults import DEFAULT_CONFIG_DIR
from app.core.errors import ExitCode
from app.core.recovery import recover_startup
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.orchestrator.recovery import recover_sessions, recover_tasks
from app.wiring import Runtime, build


class JarvisWebviewBridge:
    """JavaScript API bridge exposed to the webview frontend."""

    def __init__(self, chat: ChatOrchestrator) -> None:
        self._chat = chat

    def send_message(self, text: str) -> str:
        """Process a turn from the UI and return the assistant response."""
        stripped = text.strip()
        if not stripped:
            return ""

        if stripped.lower() == "/clear":
            self._chat.clear()
            return "현재 대화 문맥을 초기화했습니다. raw 기록은 유지됩니다."

        if stripped.lower() == "/budget":
            status = self._chat.budget_status()
            return (
                f"오늘: ${status.day.used:.2f}/${status.day.limit:.2f} "
                f"({status.day.ratio * 100:.1f}%), "
                f"이번 달: ${status.month.used:.2f}/${status.month.limit:.2f} "
                f"({status.month.ratio * 100:.1f}%)"
            )

        if stripped.lower() == "/help":
            return (
                "사용 가능한 프로토콜: /help(도움말), /clear(문맥 초기화), "
                "/budget(비용 현황), /bye(종료)"
            )

        outcome = self._chat.handle_turn(stripped)
        return outcome.text

    def clear_context(self) -> str:
        """Clear conversation prompt history."""
        self._chat.clear()
        return "Context cleared."

    def get_budget(self) -> str:
        """Return budget info."""
        status = self._chat.budget_status()
        return (
            f"오늘: ${status.day.used:.2f}/${status.day.limit:.2f} "
            f"({status.day.ratio * 100:.1f}%), "
            f"이번 달: ${status.month.used:.2f}/${status.month.limit:.2f} "
            f"({status.month.ratio * 100:.1f}%)"
        )


def run_gui(
    *,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    llm: Any | None = None,
) -> int:
    """Launch the Marvel Stark HUD GUI window."""
    runtime: Runtime | None = None
    try:
        runtime = build(config_dir, llm=llm)
        runtime.lock.acquire()
        initialize_database(runtime.memory_db)
        recover_startup(runtime.config.settings.paths.data_root, runtime.events)
        recover_sessions(
            runtime.sessions,
            policy=runtime.config.settings.session.recovery,
            events=runtime.events,
            clock=runtime.clock,
            summarizer=runtime.summarizer,
            settings=runtime.config.settings,
            ids=runtime.ids,
            sleeper=runtime.sleeper,
            random=runtime.random,
        )
        recover_tasks(runtime.task_store, runtime.events)
        try:
            runtime.indexer.sync()
        except Exception as e:
            print(f"[JARVIS RAG SYNC] Note: {e}")

        verifier = getattr(runtime.llm, "verify_model", None)
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
            verify_model=verifier if callable(verifier) else None,
            test_hook=runtime.test_hook,
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

        bridge = JarvisWebviewBridge(chat)
        html_path = Path(__file__).parent / "web" / "index.html"

        window = webview.create_window(
            title="JARVIS — STARK INDUSTRIES HUD",
            url=str(html_path.resolve()),
            js_api=bridge,
            width=1240,
            height=820,
            min_size=(1020, 680),
            background_color="#050a12",
        )

        webview.start(debug=runtime.config.settings.dev_mode)
        chat.end(reason="shutdown")
        return int(ExitCode.SUCCESS)

    except Exception as error:
        print(f"[JARVIS GUI ERROR] {error}")
        return int(ExitCode.UNHANDLED_ERROR)
    finally:
        if runtime is not None and runtime.lock.acquired:
            runtime.lock.release()

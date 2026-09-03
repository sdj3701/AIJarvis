"""Marvel Stark HUD GUI for Jarvis using PyWebView and Arc Reactor Hologram."""

from __future__ import annotations

import json
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

import webview

from app.config.defaults import DEFAULT_CONFIG_DIR
from app.core.errors import ExitCode
from app.core.recovery import recover_startup
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.orchestrator.recovery import recover_sessions, recover_tasks
from app.voice.controller import VoiceController
from app.wiring import Runtime, build, build_voice_controller


class JarvisWebviewBridge:
    """JavaScript API bridge exposed to the webview frontend."""

    def __init__(
        self,
        chat: ChatOrchestrator,
        voice_controller: VoiceController | None = None,
    ) -> None:
        self._chat = chat
        self._voice_controller = voice_controller
        self._window: webview.Window | None = None
        self._voice_enabled = voice_controller is not None
        self._mic_muted = False
        self.stop_event = threading.Event()

    def set_window(self, window: webview.Window) -> None:
        self._window = window

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

    def get_status(self) -> dict[str, Any]:
        """Return system and voice status to frontend."""
        return {
            "voice_enabled": self._voice_enabled,
            "mic_muted": self._mic_muted,
            "model": "qwen3.5:9b",
        }

    def toggle_mic(self) -> dict[str, Any]:
        """Toggle microphone listening state."""
        self._mic_muted = not self._mic_muted
        if self._window is not None:
            with suppress(Exception):
                state_json = json.dumps(not self._mic_muted)
                self._window.evaluate_js(
                    f"window.onMicStateChanged && window.onMicStateChanged({state_json});"
                )
        return {"mic_muted": self._mic_muted}

    def notify_wake(self) -> None:
        """Notify frontend that wake word '자비스' was detected."""
        if self._window is not None and not self._mic_muted:
            with suppress(Exception):
                self._window.evaluate_js("window.onJarvisWake && window.onJarvisWake();")

    def notify_transcript(self, text: str) -> None:
        """Notify frontend that user spoken command was transcribed."""
        if self._window is not None and not self._mic_muted:
            with suppress(Exception):
                escaped = json.dumps(text, ensure_ascii=False)
                self._window.evaluate_js(
                    f"window.onJarvisVoiceInput && window.onJarvisVoiceInput({escaped});"
                )

    def notify_response(self, text: str) -> None:
        """Notify frontend of assistant response."""
        if self._window is not None:
            with suppress(Exception):
                escaped = json.dumps(text, ensure_ascii=False)
                self._window.evaluate_js(
                    f"window.onJarvisVoiceOutput && window.onJarvisVoiceOutput({escaped});"
                )

    def notify_state(self, state: str) -> None:
        """Notify frontend of core state transition."""
        if self._window is not None:
            with suppress(Exception):
                escaped = json.dumps(state, ensure_ascii=False)
                self._window.evaluate_js(
                    f"window.onJarvisStateChange && window.onJarvisStateChange({escaped});"
                )


def run_gui(
    *,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    llm: Any | None = None,
) -> int:
    """Launch the Marvel Stark HUD GUI window with optional voice controller."""
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

        voice_controller: VoiceController | None = None
        if runtime.config.settings.voice.enabled:
            try:
                voice_controller = build_voice_controller(runtime, chat)
            except Exception as e:
                print(f"[JARVIS GUI VOICE NOTE] {e}")

        bridge = JarvisWebviewBridge(chat, voice_controller=voice_controller)
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
        bridge.set_window(window)

        if voice_controller is not None:
            def run_voice_loop() -> None:
                try:
                    voice_controller.run(
                        stop_event=bridge.stop_event,
                        on_wake=bridge.notify_wake,
                        on_transcript=bridge.notify_transcript,
                        on_response=bridge.notify_response,
                        on_state=bridge.notify_state,
                    )
                except Exception as ex:
                    print(f"[JARVIS VOICE LOOP ERROR] {ex}")

            voice_thread = threading.Thread(
                target=run_voice_loop,
                name="jarvis-voice-gui",
                daemon=True,
            )
            voice_thread.start()

        webview.start(debug=runtime.config.settings.dev_mode)
        bridge.stop_event.set()
        chat.end(reason="shutdown")
        return int(ExitCode.SUCCESS)

    except Exception as error:
        print(f"[JARVIS GUI ERROR] {error}")
        return int(ExitCode.UNHANDLED_ERROR)
    finally:
        if runtime is not None and runtime.lock.acquired:
            runtime.lock.release()

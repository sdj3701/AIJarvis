# 파이썬 공부 | scripts/app/ui/gui.py
# PyWebView 창과 화면에서 호출하는 파이썬 기능을 연결합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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
from app.orchestrator.tool_commands import APPROVAL_WORDS
from app.safety.gate import Verdict
from app.voice.controller import VoiceController
from app.wiring import Runtime, build, build_voice_controller


# JarvisWebviewBridge: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class JarvisWebviewBridge:
    """JavaScript API bridge exposed to the webview frontend."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: chat, voice_controller, typed_confirm_phrase.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        chat: ChatOrchestrator,
        voice_controller: VoiceController | None = None,
        typed_confirm_phrase: str = "실행합니다",
    ) -> None:
        # 오른쪽 식을 계산한 값을 self._chat에 대입합니다.
        self._chat = chat
        # self._pending_approval을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        self._pending_approval: Verdict | None = None
        # 오른쪽 식을 계산한 값을 self._typed_confirm_phrase에 대입합니다.
        self._typed_confirm_phrase = typed_confirm_phrase
        # threading.Lock()의 반환값을 self._turn_lock에 대입합니다.
        self._turn_lock = threading.Lock()
        # 오른쪽 식을 계산한 값을 self._voice_controller에 대입합니다.
        self._voice_controller = voice_controller
        # self._window을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        self._window: webview.Window | None = None
        # 오른쪽 식을 계산한 값을 self._voice_enabled에 대입합니다.
        self._voice_enabled = voice_controller is not None
        # self._mic_muted을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self._mic_muted = False
        # threading.Event()의 반환값을 self.stop_event에 대입합니다.
        self.stop_event = threading.Event()

    # set_window(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: window.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def set_window(self, window: webview.Window) -> None:
        # 오른쪽 식을 계산한 값을 self._window에 대입합니다.
        self._window = window

    # send_message(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text.
    # 반환 타입 힌트: 문자열(str).
    def send_message(self, text: str) -> str:
        """Process a turn from the UI and return the assistant response."""
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._turn_lock:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return self._send_message(text)

    # _send_message(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text.
    # 반환 타입 힌트: 문자열(str).
    def _send_message(self, text: str) -> str:
        # text.strip()의 반환값을 stripped에 대입합니다.
        stripped = text.strip()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not stripped.
        if not stripped:
            # ''을 반환하고 이 함수의 실행을 끝냅니다.
            return ""

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._pending_approval is not None.
        if self._pending_approval is not None:
            # 오른쪽 식을 계산한 값을 verdict에 대입합니다.
            verdict = self._pending_approval
            # self._pending_approval을 아직 값이 없음을 뜻하는 None으로 설정합니다.
            self._pending_approval = None
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: stripped.lower() in {'n', 'no',
            # '취소', '아니오'}.
            if stripped.lower() in {"n", "no", "취소", "아니오"}:
                # self._chat.discard_pending_approval()을 호출해 작업을 수행합니다.
                self._chat.discard_pending_approval(cause="user_deny")
                # '작업 요청을 취소했습니다.'을 반환하고 이 함수의 실행을 끝냅니다.
                return "작업 요청을 취소했습니다."
            # 오른쪽 식을 계산한 값을 expected에 대입합니다.
            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
            expected = self._typed_confirm_phrase if verdict.decision == "typed_confirm" else "y"
            # 오른쪽 식을 계산한 값을 confirmed에 대입합니다.
            confirmed = stripped == expected or (
                verdict.decision == "confirm" and stripped.rstrip(".!") in APPROVAL_WORDS
            )
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: confirmed and
            # self._chat.has_pending_approval().
            if confirmed and self._chat.has_pending_approval():
                # 오른쪽 식을 계산한 값을 store에 대입합니다.
                store = self._chat.approval_store
                # 오른쪽 식을 계산한 값을 ctx에 대입합니다.
                ctx = self._chat.pending_context
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: store is not None and ctx is
                # not None.
                if store is not None and ctx is not None:
                    # store.grant()의 반환값을 ticket에 대입합니다.
                    ticket = store.grant(verdict, ctx=ctx, method=(
                        "user_typed_phrase" if verdict.decision == "typed_confirm" else "user_text"
                    ))
                    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                    return self._format_outcome(self._chat.resume_after_approval(ticket))
            # self._chat.discard_pending_approval()을 호출해 작업을 수행합니다.
            self._chat.discard_pending_approval(cause="new_input")
            # '확인 문구가 일치하지 않아 취소했습니다. 작업을 다시 요청하세요.'을 반환하고 이
            # 함수의 실행을 끝냅니다.
            return "확인 문구가 일치하지 않아 취소했습니다. 작업을 다시 요청하세요."

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: stripped.lower() == '/clear'.
        if stripped.lower() == "/clear":
            # self._chat.clear()을 호출해 작업을 수행합니다.
            self._chat.clear()
            # '현재 대화 문맥을 초기화했습니다. raw 기록은 유지됩니다.'을 반환하고 이 함수의
            # 실행을 끝냅니다.
            return "현재 대화 문맥을 초기화했습니다. raw 기록은 유지됩니다."

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: stripped.lower() == '/budget'.
        if stripped.lower() == "/budget":
            # self._chat.budget_status()의 반환값을 status에 대입합니다.
            status = self._chat.budget_status()
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            return (
                f"오늘: ${status.day.used:.2f}/${status.day.limit:.2f} "
                f"({status.day.ratio * 100:.1f}%), "
                f"이번 달: ${status.month.used:.2f}/${status.month.limit:.2f} "
                f"({status.month.ratio * 100:.1f}%)"
            )

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: stripped.lower() == '/help'.
        if stripped.lower() == "/help":
            # 문자열 결과를 반환하고 함수를 끝냅니다.
            return (
                "사용 가능한 프로토콜: /help(도움말), /clear(문맥 초기화), "
                "/details(직전 상세), /status(응답 룰북), "
                "/recall 검색어(과거 대화), /recall status|reindex|forget 턴ID, "
                "/commands(명령 기억), /learn 표현 => /open_app 앱이름(명령 뜻 저장), "
                "/budget(비용 현황), /apps(실행 허용 앱), /apps revoke ID(허용 취소), /bye(종료)"
            )

        # self._chat.handle_turn()의 반환값을 outcome에 대입합니다.
        outcome = self._chat.handle_turn(stripped)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._format_outcome(outcome)

    # _format_outcome(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: outcome.
    # 반환 타입 힌트: 문자열(str).
    def _format_outcome(self, outcome: Any) -> str:
        # 오른쪽 식을 계산한 값을 self._pending_approval에 대입합니다.
        self._pending_approval = outcome.pending_approval
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._pending_approval is not None.
        if self._pending_approval is not None:
            # 오른쪽 식을 계산한 값을 expected에 대입합니다.
            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
            expected = (self._typed_confirm_phrase
                        if self._pending_approval.decision == "typed_confirm" else "y")
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            return f"{outcome.text}\n{self._pending_approval.reason}\n승인: {expected} / 취소: n"
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return str(outcome.display_text)

    # get_response_detail(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    def get_response_detail(self) -> str:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._chat.response_detail()

    # clear_context(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    def clear_context(self) -> str:
        """Clear conversation prompt history."""
        # self._chat.clear()을 호출해 작업을 수행합니다.
        self._chat.clear()
        # 'Context cleared.'을 반환하고 이 함수의 실행을 끝냅니다.
        return "Context cleared."

    # get_app_permissions(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: list[dict[str, str]].
    def get_app_permissions(self) -> list[dict[str, str]]:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._turn_lock:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return self._chat.app_permissions()

    # revoke_app_permission(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: record_id.
    # 반환 타입 힌트: 문자열(str).
    def revoke_app_permission(self, record_id: str) -> str:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._turn_lock:
            # self._pending_approval을 아직 값이 없음을 뜻하는 None으로 설정합니다.
            self._pending_approval = None
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return str(self._chat.handle_turn(f"/apps revoke {record_id}").text)

    # get_budget(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    def get_budget(self) -> str:
        """Return budget info."""
        # self._chat.budget_status()의 반환값을 status에 대입합니다.
        status = self._chat.budget_status()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
        return (
            f"오늘: ${status.day.used:.2f}/${status.day.limit:.2f} "
            f"({status.day.ratio * 100:.1f}%), "
            f"이번 달: ${status.month.used:.2f}/${status.month.limit:.2f} "
            f"({status.month.ratio * 100:.1f}%)"
        )

    # get_status(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: dict[str, Any].
    def get_status(self) -> dict[str, Any]:
        """Return system and voice status to frontend."""
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return {
            "voice_enabled": self._voice_enabled,
            "mic_muted": self._mic_muted,
            "model": "qwen3.5:9b",
        }

    # toggle_mic(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: dict[str, Any].
    def toggle_mic(self) -> dict[str, Any]:
        """Toggle microphone listening state."""
        # 오른쪽 식을 계산한 값을 self._mic_muted에 대입합니다.
        self._mic_muted = not self._mic_muted
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._window is not None.
        if self._window is not None:
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with suppress(Exception):
                # json.dumps()의 반환값을 state_json에 대입합니다.
                state_json = json.dumps(not self._mic_muted)
                # self._window.evaluate_js()을 호출해 작업을 수행합니다.
                self._window.evaluate_js(
                    f"window.onMicStateChanged && window.onMicStateChanged({state_json});"
                )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return {"mic_muted": self._mic_muted}

    # notify_wake(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def notify_wake(self) -> None:
        """Notify frontend that wake word '자비스' was detected."""
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._window is not None and (not
        # self._mic_muted).
        if self._window is not None and not self._mic_muted:
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with suppress(Exception):
                # self._window.evaluate_js()을 호출해 작업을 수행합니다.
                self._window.evaluate_js("window.onJarvisWake && window.onJarvisWake();")

    # notify_transcript(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def notify_transcript(self, text: str) -> None:
        """Notify frontend that user spoken command was transcribed."""
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._window is not None and (not
        # self._mic_muted).
        if self._window is not None and not self._mic_muted:
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with suppress(Exception):
                # json.dumps()의 반환값을 escaped에 대입합니다.
                escaped = json.dumps(text, ensure_ascii=False)
                # self._window.evaluate_js()을 호출해 작업을 수행합니다.
                self._window.evaluate_js(
                    f"window.onJarvisVoiceInput && window.onJarvisVoiceInput({escaped});"
                )

    # notify_response(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def notify_response(self, text: str) -> None:
        """Notify frontend of assistant response."""
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._window is not None.
        if self._window is not None:
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with suppress(Exception):
                # json.dumps()의 반환값을 escaped에 대입합니다.
                escaped = json.dumps(text, ensure_ascii=False)
                # self._window.evaluate_js()을 호출해 작업을 수행합니다.
                self._window.evaluate_js(
                    f"window.onJarvisVoiceOutput && window.onJarvisVoiceOutput({escaped});"
                )

    # notify_state(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: state.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def notify_state(self, state: str) -> None:
        """Notify frontend of core state transition."""
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._window is not None.
        if self._window is not None:
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with suppress(Exception):
                # json.dumps()의 반환값을 escaped에 대입합니다.
                escaped = json.dumps(state, ensure_ascii=False)
                # self._window.evaluate_js()을 호출해 작업을 수행합니다.
                self._window.evaluate_js(
                    f"window.onJarvisStateChange && window.onJarvisStateChange({escaped});"
                )


# run_gui(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: config_dir, llm.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 정수(int).
def run_gui(
    *,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    llm: Any | None = None,
) -> int:
    """Launch the Marvel Stark HUD GUI window with optional voice controller."""
    # runtime을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    runtime: Runtime | None = None
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # build()의 반환값을 runtime에 대입합니다.
        runtime = build(config_dir, llm=llm)
        # runtime.lock.acquire()을 호출해 작업을 수행합니다.
        runtime.lock.acquire()
        # initialize_database()을 호출해 작업을 수행합니다.
        initialize_database(runtime.memory_db)
        # recover_startup()을 호출해 작업을 수행합니다.
        recover_startup(runtime.config.settings.paths.data_root, runtime.events)
        # recover_sessions()을 호출해 작업을 수행합니다.
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
        # recover_tasks()을 호출해 작업을 수행합니다.
        recover_tasks(runtime.task_store, runtime.events)
        # Bring up and verify local models before the first embedding sync.
        verifier = getattr(runtime.llm, "verify_model", None)
        if callable(verifier):
            verifier()

        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # runtime.indexer.sync()을 호출해 작업을 수행합니다.
            runtime.indexer.sync()
        # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except Exception as e:
            # 값을 텍스트로 출력합니다.
            print(f"[JARVIS RAG SYNC] Note: {e}")

        # ChatOrchestrator()의 반환값을 chat에 대입합니다.
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
            verify_model=None,  # Verified before indexing above.
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
        # chat.start()을 호출해 작업을 수행합니다.
        chat.start()

        # voice_controller을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        voice_controller: VoiceController | None = None
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: runtime.config.settings.voice.enabled.
        if runtime.config.settings.voice.enabled:
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # build_voice_controller()의 반환값을 voice_controller에 대입합니다.
                voice_controller = build_voice_controller(runtime, chat)
            # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
            except Exception as e:
                # 값을 텍스트로 출력합니다.
                print(f"[JARVIS GUI VOICE NOTE] {e}")

        # JarvisWebviewBridge()의 반환값을 bridge에 대입합니다.
        bridge = JarvisWebviewBridge(
            chat, voice_controller=voice_controller,
            typed_confirm_phrase=runtime.config.policies.tools.approval.typed_confirm_phrase,
        )
        # 오른쪽 식을 계산한 값을 html_path에 대입합니다.
        html_path = Path(__file__).parent / "web" / "index.html"

        # webview.create_window()의 반환값을 window에 대입합니다.
        window = webview.create_window(
            title="JARVIS — STARK INDUSTRIES HUD",
            url=str(html_path.resolve()),
            js_api=bridge,
            width=1240,
            height=820,
            min_size=(1020, 680),
            background_color="#050a12",
        )
        # bridge.set_window()을 호출해 작업을 수행합니다.
        bridge.set_window(window)

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: voice_controller is not None.
        if voice_controller is not None:
            # run_voice_loop(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
            # 반환 타입 힌트: 별도 결과 없음(None).
            def run_voice_loop() -> None:
                # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를
                # 처리합니다.
                try:
                    # voice_controller.run()을 호출해 작업을 수행합니다.
                    voice_controller.run(
                        stop_event=bridge.stop_event,
                        on_wake=bridge.notify_wake,
                        on_transcript=bridge.notify_transcript,
                        on_response=bridge.notify_response,
                        on_state=bridge.notify_state,
                    )
                # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
                except Exception as ex:
                    # 값을 텍스트로 출력합니다.
                    print(f"[JARVIS VOICE LOOP ERROR] {ex}")

            # threading.Thread()의 반환값을 voice_thread에 대입합니다.
            voice_thread = threading.Thread(
                target=run_voice_loop,
                name="jarvis-voice-gui",
                daemon=True,
            )
            # voice_thread.start()을 호출해 작업을 수행합니다.
            voice_thread.start()

        # webview.start()을 호출해 작업을 수행합니다.
        webview.start(debug=runtime.config.settings.dev_mode)
        # bridge.stop_event.set()을 호출해 작업을 수행합니다.
        bridge.stop_event.set()
        # chat.end()을 호출해 작업을 수행합니다.
        chat.end(reason="shutdown")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return int(ExitCode.SUCCESS)

    # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except Exception as error:
        # 값을 텍스트로 출력합니다.
        print(f"[JARVIS GUI ERROR] {error}")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return int(ExitCode.UNHANDLED_ERROR)
    # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
    finally:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: runtime is not None and
        # runtime.lock.acquired.
        if runtime is not None and runtime.lock.acquired:
            # runtime.lock.release()을 호출해 작업을 수행합니다.
            runtime.lock.release()

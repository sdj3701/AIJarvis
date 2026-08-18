"""Text CLI: slash commands, tool-approval prompts, and the chat turn loop.

Callers may omit ``chat`` to keep the echo fallback used by Phase 0 unit tests.
"""

from __future__ import annotations

from typing import TextIO

from app.core.errors import ExitCode
from app.memory.commands import try_handle_memory_command
from app.orchestrator.loop import ChatOrchestrator, TurnOutcome
from app.safety.approval import GrantMethod

HELP_TEXT = (
    "사용 가능한 명령: /help(도움말), /clear(현재 문맥 초기화), "
    "/budget(비용 현황), /index(문서 동기화), /search <질의>(웹·문서 검색), "
    "/open_app <앱>(허용 앱 실행), /open_folder <root> [경로], "
    "/open_url <https://...>, /create_file <root> <파일> [내용], /bye(종료), "
    "기억해: ..., 틀림: A → B, /memory list|confirm|edit|export, /forget <id>"
)
WELCOME_TEXT = "Jarvis 로컬 CLI입니다. /help를 입력하면 도움말을 볼 수 있습니다."


def _write(stream: TextIO, text: str) -> None:
    stream.write(text)
    stream.write("\n")
    stream.flush()


def _budget_text(chat: ChatOrchestrator) -> str:
    status = chat.budget_status()
    return (
        f"오늘: ${status.day.used:.2f}/{status.day.limit:.2f} "
        f"({status.day.ratio * 100:.1f}%), "
        f"이번 달: ${status.month.used:.2f}/{status.month.limit:.2f} "
        f"({status.month.ratio * 100:.1f}%)"
    )


def _handle_approval(
    chat: ChatOrchestrator,
    outcome: TurnOutcome,
    *,
    input_stream: TextIO,
    output_stream: TextIO,
    typed_phrase: str,
) -> str:
    verdict = outcome.pending_approval
    if verdict is None:
        return outcome.text
    _write(output_stream, verdict.display)
    if verdict.decision == "typed_confirm":
        _write(output_stream, f"계속하려면 다음 문구를 그대로 입력하세요: {typed_phrase}")
    else:
        _write(output_stream, "실행하려면 y, 취소하려면 n을 입력하세요.")

    while True:
        output_stream.write("승인> ")
        output_stream.flush()
        answer = input_stream.readline()
        if answer == "":
            chat.discard_pending_approval(cause="shutdown")
            return "승인 대기가 취소되었습니다."
        response = answer.rstrip("\r\n").strip()
        lowered = response.lower()
        if lowered in {"n", "no", "아니오", "취소"}:
            chat.discard_pending_approval(cause="user_deny")
            return "작업을 실행하지 않았습니다."
        if verdict.decision == "typed_confirm":
            if response != typed_phrase:
                chat.discard_pending_approval(cause="user_deny")
                return "확인 문구가 일치하지 않아 작업을 취소했습니다."
            method: GrantMethod = "user_typed_phrase"
        elif lowered in {"y", "yes", "예", "ㅇ"}:
            method = "user_text"
        else:
            _write(output_stream, "y/n 또는 확인 문구를 입력하세요.")
            continue

        if chat.approval_store is None or chat.pending_context is None:
            return "승인 저장소가 구성되지 않았습니다."
        ticket = chat.approval_store.grant(
            verdict,
            ctx=chat.pending_context,
            method=method,
        )
        resumed = chat.resume_after_approval(ticket)
        return resumed.text


def _handle_turn_with_approval(
    text: str,
    *,
    chat: ChatOrchestrator,
    input_stream: TextIO,
    output_stream: TextIO,
    typed_phrase: str,
) -> str:
    if chat.has_pending_approval():
        chat.discard_pending_approval(cause="new_input")
    outcome = chat.handle_turn(text)
    if outcome.pending_approval is not None:
        return _handle_approval(
            chat,
            outcome,
            input_stream=input_stream,
            output_stream=output_stream,
            typed_phrase=typed_phrase,
        )
    return outcome.text


def _handle_line(
    text: str,
    output_stream: TextIO,
    *,
    chat: ChatOrchestrator | None,
    input_stream: TextIO | None = None,
    typed_phrase: str = "실행합니다",
) -> bool:
    command = text.strip().lower()
    if command == "/help":
        _write(output_stream, HELP_TEXT)
        return True
    if command == "/bye":
        if chat is not None:
            chat.discard_pending_approval(cause="shutdown")
            chat.end(reason="bye")
        _write(output_stream, "안전하게 종료합니다.")
        return False
    if command == "/clear":
        if chat is not None:
            chat.clear()
            chat.discard_pending_approval(cause="new_input")
        _write(output_stream, "현재 대화 문맥을 초기화했습니다. raw 기록은 유지됩니다.")
        return True
    if command == "/budget":
        _write(output_stream, "비용 기록이 없습니다." if chat is None else _budget_text(chat))
        return True
    if command == "/index":
        if chat is None:
            _write(output_stream, "문서 인덱서가 구성되지 않았습니다.")
        else:
            chat.start()
            _write(output_stream, chat.handle_index())
        return True
    if not text.strip():
        return True
    if chat is not None:
        chat.start()
        memory_ctx = chat.memory_command_context()
        if memory_ctx is not None:
            memory_result = try_handle_memory_command(text, memory_ctx)
            if memory_result is not None:
                _write(output_stream, memory_result.message)
                return memory_result.ok or True
        if input_stream is None:
            _write(output_stream, chat.handle_turn(text).text)
        else:
            _write(
                output_stream,
                _handle_turn_with_approval(
                    text,
                    chat=chat,
                    input_stream=input_stream,
                    output_stream=output_stream,
                    typed_phrase=typed_phrase,
                ),
            )
        return True
    _write(output_stream, text)
    return True


def run_cli(
    *,
    input_stream: TextIO,
    output_stream: TextIO,
    once: str | None = None,
    chat: ChatOrchestrator | None = None,
    typed_confirm_phrase: str = "실행합니다",
) -> int:
    """Run local chat; direct unit callers may omit chat for the Phase 0 echo fallback."""
    try:
        if chat is not None:
            chat.start()
        if once is not None:
            keep_running = _handle_line(
                once,
                output_stream,
                chat=chat,
                input_stream=input_stream,
                typed_phrase=typed_confirm_phrase,
            )
            if keep_running and chat is not None:
                chat.discard_pending_approval(cause="shutdown")
                chat.end(reason="bye")
            return int(ExitCode.SUCCESS)

        _write(output_stream, WELCOME_TEXT)
        while True:
            output_stream.write("Jarvis> ")
            output_stream.flush()
            line = input_stream.readline()
            if line == "":
                if chat is not None:
                    chat.discard_pending_approval(cause="shutdown")
                    chat.end(reason="bye")
                _write(output_stream, "안전하게 종료합니다.")
                return int(ExitCode.SUCCESS)
            text = line.rstrip("\r\n")
            if not _handle_line(
                text,
                output_stream,
                chat=chat,
                input_stream=input_stream,
                typed_phrase=typed_confirm_phrase,
            ):
                return int(ExitCode.SUCCESS)
    except KeyboardInterrupt:
        if chat is not None:
            chat.cancel_current()
            chat.end(reason="discarded")
        _write(output_stream, "\n입력을 중단하고 안전하게 종료합니다.")
        return int(ExitCode.INTERRUPTED)

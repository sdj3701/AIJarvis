"""Phase 1 text chat interface and command dispatcher."""

from __future__ import annotations

from typing import TextIO

from app.core.errors import ExitCode
from app.orchestrator.loop import ChatOrchestrator

HELP_TEXT = (
    "사용 가능한 명령: /help(도움말), /clear(현재 문맥 초기화), "
    "/budget(비용 현황), /bye(종료)"
)
WELCOME_TEXT = "Jarvis Phase 1 로컬 CLI입니다. /help를 입력하면 도움말을 볼 수 있습니다."


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


def _handle_line(
    text: str,
    output_stream: TextIO,
    *,
    chat: ChatOrchestrator | None,
) -> bool:
    command = text.strip().lower()
    if command == "/help":
        _write(output_stream, HELP_TEXT)
        return True
    if command == "/bye":
        if chat is not None:
            chat.end(reason="bye")
        _write(output_stream, "안전하게 종료합니다.")
        return False
    if command == "/clear":
        if chat is not None:
            chat.clear()
        _write(output_stream, "현재 대화 문맥을 초기화했습니다. raw 기록은 유지됩니다.")
        return True
    if command == "/budget":
        _write(output_stream, "비용 기록이 없습니다." if chat is None else _budget_text(chat))
        return True
    if not text.strip():
        return True
    if chat is not None:
        _write(output_stream, chat.handle_turn(text).text)
        return True
    _write(output_stream, text)
    return True


def run_cli(
    *,
    input_stream: TextIO,
    output_stream: TextIO,
    once: str | None = None,
    chat: ChatOrchestrator | None = None,
) -> int:
    """Run local chat; direct unit callers may omit chat for the Phase 0 echo fallback."""
    try:
        if chat is not None:
            chat.start()
        if once is not None:
            keep_running = _handle_line(once, output_stream, chat=chat)
            if keep_running and chat is not None:
                chat.end(reason="bye")
            return int(ExitCode.SUCCESS)

        _write(output_stream, WELCOME_TEXT)
        while True:
            output_stream.write("Jarvis> ")
            output_stream.flush()
            line = input_stream.readline()
            if line == "":
                if chat is not None:
                    chat.end(reason="bye")
                _write(output_stream, "안전하게 종료합니다.")
                return int(ExitCode.SUCCESS)
            text = line.rstrip("\r\n")
            if not _handle_line(text, output_stream, chat=chat):
                return int(ExitCode.SUCCESS)
    except KeyboardInterrupt:
        if chat is not None:
            chat.cancel_current()
            chat.end(reason="discarded")
        _write(output_stream, "\n입력을 중단하고 안전하게 종료합니다.")
        return int(ExitCode.INTERRUPTED)

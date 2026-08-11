"""Phase 0 text interface with no external-service calls."""

from __future__ import annotations

from typing import TextIO

from app.core.errors import ExitCode

HELP_TEXT = "사용 가능한 명령: /help(도움말), /bye(종료)"
WELCOME_TEXT = "Jarvis Phase 0 CLI입니다. /help를 입력하면 도움말을 볼 수 있습니다."


def _write(stream: TextIO, text: str) -> None:
    stream.write(text)
    stream.write("\n")
    stream.flush()


def _handle_line(text: str, output_stream: TextIO) -> bool:
    command = text.strip().lower()
    if command == "/help":
        _write(output_stream, HELP_TEXT)
        return True
    if command == "/bye":
        _write(output_stream, "안전하게 종료합니다.")
        return False
    _write(output_stream, text)
    return True


def run_cli(
    *,
    input_stream: TextIO,
    output_stream: TextIO,
    once: str | None = None,
) -> int:
    """Run an echo loop; return documented process exit codes instead of exiting."""
    try:
        if once is not None:
            _handle_line(once, output_stream)
            return int(ExitCode.SUCCESS)

        _write(output_stream, WELCOME_TEXT)
        while True:
            output_stream.write("Jarvis> ")
            output_stream.flush()
            line = input_stream.readline()
            if line == "":
                _write(output_stream, "안전하게 종료합니다.")
                return int(ExitCode.SUCCESS)
            text = line.rstrip("\r\n")
            if not _handle_line(text, output_stream):
                return int(ExitCode.SUCCESS)
    except KeyboardInterrupt:
        _write(output_stream, "\n입력을 중단하고 안전하게 종료합니다.")
        return int(ExitCode.INTERRUPTED)

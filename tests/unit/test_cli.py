from __future__ import annotations

from io import StringIO

import pytest

from app.cli import HELP_TEXT, WELCOME_TEXT, run_cli
from app.core.errors import ExitCode

pytestmark = pytest.mark.phase0


class InterruptingInput(StringIO):
    def readline(self, size: int = -1, /) -> str:
        del size
        raise KeyboardInterrupt


def test_cli_supports_help_echo_and_bye() -> None:
    output = StringIO()

    exit_code = run_cli(input_stream=StringIO("/help\n안녕하세요\n/bye\n"), output_stream=output)

    rendered = output.getvalue()
    assert exit_code == ExitCode.SUCCESS
    assert WELCOME_TEXT in rendered
    assert HELP_TEXT in rendered
    assert "안녕하세요" in rendered
    assert "안전하게 종료합니다." in rendered


def test_cli_ctrl_c_returns_130() -> None:
    output = StringIO()

    exit_code = run_cli(input_stream=InterruptingInput(), output_stream=output)

    assert exit_code == ExitCode.INTERRUPTED
    assert "안전하게 종료" in output.getvalue()


def test_cli_once_echoes_without_prompt() -> None:
    output = StringIO()

    exit_code = run_cli(input_stream=StringIO(), output_stream=output, once="한 번")

    assert exit_code == 0
    assert output.getvalue() == "한 번\n"

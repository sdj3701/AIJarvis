# 파이썬 공부 | scripts/tests/unit/test_cli.py
# cli 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

from __future__ import annotations

from io import StringIO

import pytest

from app.cli import HELP_TEXT, WELCOME_TEXT, run_cli
from app.core.errors import ExitCode

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase0


# InterruptingInput: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: StringIO.
class InterruptingInput(StringIO):
    # readline(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: size.
    # 반환 타입 힌트: 문자열(str).
    def readline(self, size: int = -1, /) -> str:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del size
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise KeyboardInterrupt


# pytest가 test_cli_supports_help_echo_and_bye()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_cli_supports_help_echo_and_bye() -> None:
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()

    # run_cli()의 반환값을 exit_code에 대입합니다.
    exit_code = run_cli(input_stream=StringIO("/help\n안녕하세요\n/bye\n"), output_stream=output)

    # output.getvalue()의 반환값을 rendered에 대입합니다.
    rendered = output.getvalue()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert exit_code == ExitCode.SUCCESS
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert WELCOME_TEXT in rendered
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert HELP_TEXT in rendered
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "안녕하세요" in rendered
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "안전하게 종료합니다." in rendered


# pytest가 test_cli_ctrl_c_returns_130()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_cli_ctrl_c_returns_130() -> None:
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()

    # run_cli()의 반환값을 exit_code에 대입합니다.
    exit_code = run_cli(input_stream=InterruptingInput(), output_stream=output)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert exit_code == ExitCode.INTERRUPTED
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "안전하게 종료" in output.getvalue()


# pytest가 test_cli_once_echoes_without_prompt()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_cli_once_echoes_without_prompt() -> None:
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()

    # run_cli()의 반환값을 exit_code에 대입합니다.
    exit_code = run_cli(input_stream=StringIO(), output_stream=output, once="한 번")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert exit_code == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert output.getvalue() == "한 번\n"


# pytest가 test_phase0_cli_echoes_later_phase_commands()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_phase0_cli_echoes_later_phase_commands() -> None:
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()

    # run_cli()의 반환값을 exit_code에 대입합니다.
    exit_code = run_cli(input_stream=StringIO("/clear\n/bye\n"), output_stream=output)

    # output.getvalue()의 반환값을 rendered에 대입합니다.
    rendered = output.getvalue()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert exit_code == ExitCode.SUCCESS
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "/clear" in rendered
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "현재 대화 문맥을 초기화" not in rendered

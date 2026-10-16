# 파이썬 공부 | scripts/app/__main__.py
# 프로그램 시작점입니다. 실행 옵션을 읽고 CLI 또는 GUI를 시작합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Command-line entry point for ``python -m app``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config.defaults import DEFAULT_CONFIG_DIR
from app.wiring import run_application


# 터미널 실행 옵션의 이름, 타입, 기본값을 argparse에 등록합니다.
# --once, --voice, --gui는 같은 그룹에서 하나만 선택할 수 있습니다.
# 반환 타입 힌트: argparse.ArgumentParser.
def _parser() -> argparse.ArgumentParser:
    # argparse는 --gui 같은 명령줄 옵션을 해석하는 표준 라이브러리입니다.
    parser = argparse.ArgumentParser(description="Jarvis local CLI / Marvel HUD")
    # --config-dir로 받은 문자열을 Path 객체로 변환합니다. 생략하면 기본 폴더를 사용합니다.
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    # 서로 동시에 선택할 수 없는 옵션 그룹을 만듭니다.
    mode = parser.add_mutually_exclusive_group()
    # mode.add_argument()을 호출해 작업을 수행합니다.
    mode.add_argument("--once", help="한 줄 입력하고 그대로 출력한 뒤 종료합니다.")
    # mode.add_argument()을 호출해 작업을 수행합니다.
    mode.add_argument(
        "--voice",
        # --voice가 있으면 True, 생략하면 False가 됩니다.
        action="store_true",
        help="마이크를 열고 '자비스' 로컬 웨이크워드를 기다립니다.",
    )
    # mode.add_argument()을 호출해 작업을 수행합니다.
    mode.add_argument(
        "--gui",
        action="store_true",
        help="마블 스타크 인더스트리 아크 리액터 HUD 인터랙티브 창을 엽니다.",
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return parser


# 실행 옵션을 해석하고 GUI 또는 터미널 실행 함수로 넘깁니다.
# argv=None이면 argparse가 실제 명령줄 인자를 사용합니다.
# 입력: argv.
# 반환 타입 힌트: 정수(int).
def main(argv: list[str] | None = None) -> int:
    """Parse CLI flags and hand off to ``run_application`` or ``run_gui``."""
    # 옵션 해석 결과를 args 객체에 담습니다. args.voice처럼 속성으로 읽습니다.
    args = _parser().parse_args(argv)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: getattr(args, 'gui', False).
    if getattr(args, "gui", False):
        from app.ui.gui import run_gui

        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return run_gui(config_dir=args.config_dir)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return run_application(
        config_dir=args.config_dir,
        input_stream=sys.stdin,
        output_stream=sys.stdout,
        error_stream=sys.stderr,
        once=args.once,
        voice=args.voice,
    )


# 이 파일을 실행 진입점으로 사용할 때만 아래 코드를 실행합니다. import할 때는 실행하지 않습니다.
if __name__ == "__main__":
    # SystemExit 예외로 프로그램 종료를 요청합니다. 전달한 값은 종료 상태를 나타냅니다.
    raise SystemExit(main())

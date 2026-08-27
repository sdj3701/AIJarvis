"""Command-line entry point for ``python -m app``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config.defaults import DEFAULT_CONFIG_DIR
from app.wiring import run_application


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jarvis local CLI / Marvel HUD")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", help="한 줄 입력하고 그대로 출력한 뒤 종료합니다.")
    mode.add_argument(
        "--voice",
        action="store_true",
        help="마이크를 열고 '자비스' 로컬 웨이크워드를 기다립니다.",
    )
    mode.add_argument(
        "--gui",
        action="store_true",
        help="마블 스타크 인더스트리 아크 리액터 HUD 인터랙티브 창을 엽니다.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse CLI flags and hand off to ``run_application`` or ``run_gui``."""
    args = _parser().parse_args(argv)
    if getattr(args, "gui", False):
        from app.ui.gui import run_gui

        return run_gui(config_dir=args.config_dir)
    return run_application(
        config_dir=args.config_dir,
        input_stream=sys.stdin,
        output_stream=sys.stdout,
        error_stream=sys.stderr,
        once=args.once,
        voice=args.voice,
    )


if __name__ == "__main__":
    raise SystemExit(main())

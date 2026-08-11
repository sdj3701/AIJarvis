"""Command-line entry point for ``python -m app``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config.loader import DEFAULT_CONFIG_DIR
from app.wiring import run_application


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jarvis Phase 0 CLI")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--once", help="한 번 echo한 뒤 종료합니다.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return run_application(
        config_dir=args.config_dir,
        input_stream=sys.stdin,
        output_stream=sys.stdout,
        error_stream=sys.stderr,
        once=args.once,
    )


if __name__ == "__main__":
    raise SystemExit(main())

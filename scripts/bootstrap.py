"""Create the Jarvis data tree and initialize its SQLite database."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import ConfigError, JarvisError, exit_code_for
from app.memory.migrations import initialize_database

DEFAULT_DATA_ROOT = Path(r"D:\Jarvis")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_SOURCE = REPOSITORY_ROOT / "config"
DEFAULT_MIN_FREE_BYTES = 5 * 1024**3

TREE_DIRECTORIES = (
    "config",
    "memory/raw",
    "memory/export",
    "docs/notes",
    "skills",
    "state/quarantine",
    "logs",
    "models",
    "backups",
)
CONFIG_COPIES = {
    "settings.example.yaml": "settings.yaml",
    "privacy.example.yaml": "privacy.yaml",
    "tools.example.yaml": "tools.yaml",
}


@dataclass(frozen=True, slots=True)
class BootstrapAction:
    kind: str
    status: str
    target: Path


@dataclass(frozen=True, slots=True)
class BootstrapReport:
    data_root: Path
    database_path: Path
    free_bytes: int
    actions: tuple[BootstrapAction, ...]


def create_tree(data_root: Path) -> tuple[BootstrapAction, ...]:
    """Create all required directories, reporting existing paths as skipped."""
    actions: list[BootstrapAction] = []
    for relative in TREE_DIRECTORIES:
        target = data_root / Path(relative)
        existed = target.is_dir()
        target.mkdir(parents=True, exist_ok=True)
        actions.append(BootstrapAction("directory", "skipped" if existed else "created", target))
    return tuple(actions)


def _copy_initial_configs(data_root: Path, source: Path) -> tuple[BootstrapAction, ...]:
    actions: list[BootstrapAction] = []
    for source_name, target_name in CONFIG_COPIES.items():
        source_path = source / source_name
        target_path = data_root / "config" / target_name
        if not source_path.is_file():
            raise ConfigError("초기 설정 원본 파일이 없습니다.", {"source": str(source_path)})
        try:
            with source_path.open("rb") as input_file, target_path.open("xb") as output_file:
                shutil.copyfileobj(input_file, output_file)
        except FileExistsError:
            actions.append(BootstrapAction("config", "skipped", target_path))
        else:
            actions.append(BootstrapAction("config", "copied", target_path))
    return tuple(actions)


def _verify_writable(data_root: Path) -> None:
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".bootstrap-write-", dir=data_root / "state", delete=False
        ) as probe:
            probe.write(b"ok")
            probe.flush()
            os.fsync(probe.fileno())
            probe_path = Path(probe.name)
        probe_path.unlink()
    except OSError as error:
        raise ConfigError(
            "데이터 루트에 쓸 수 없습니다.",
            {"data_root": str(data_root), "error_type": type(error).__name__},
        ) from error


def bootstrap(
    data_root: Path = DEFAULT_DATA_ROOT,
    *,
    config_source: Path = DEFAULT_CONFIG_SOURCE,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
) -> BootstrapReport:
    """Run the complete idempotent bootstrap sequence."""
    if min_free_bytes < 0:
        raise ValueError("min_free_bytes must be non-negative")
    actions = list(create_tree(data_root))
    _verify_writable(data_root)
    free_bytes = shutil.disk_usage(data_root).free
    if free_bytes < min_free_bytes:
        raise ConfigError(
            "데이터 저장 공간이 부족합니다.",
            {"required_bytes": min_free_bytes, "free_bytes": free_bytes},
        )
    actions.extend(_copy_initial_configs(data_root, config_source))

    database_path = data_root / "memory" / "jarvis.sqlite3"
    database_result = initialize_database(database_path)
    actions.append(
        BootstrapAction(
            "database", "created" if database_result.created else "verified", database_path
        )
    )
    return BootstrapReport(data_root, database_path, free_bytes, tuple(actions))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jarvis 데이터 폴더와 DB를 초기화합니다.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=DEFAULT_MIN_FREE_BYTES / 1024**3,
        help="필요한 최소 여유 공간(GB)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.min_free_gb < 0:
        _parser().error("--min-free-gb는 0 이상이어야 합니다.")
    try:
        report = bootstrap(args.data_root, min_free_bytes=int(args.min_free_gb * 1024**3))
    except JarvisError as error:
        print(f"실패: {error.user_message}", file=sys.stderr)
        return int(exit_code_for(error))

    labels = {"created": "완료", "copied": "완료", "verified": "확인", "skipped": "건너뜀"}
    for action in report.actions:
        print(f"[{labels[action.status]}] {action.kind}: {action.target}")
    print(f"남은 공간: {report.free_bytes / 1024**3:.2f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

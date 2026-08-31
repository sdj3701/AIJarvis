from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.budget import BudgetGuard
from app.core.errors import ExitCode
from app.llm.fake import FakeLLMClient
from app.llm.ollama_client import OllamaClient
from app.memory.store import SQLiteSessionStore
from app.ui.single_instance import SingleInstanceLock
from app.wiring import build, run_application
from scripts.bootstrap import create_tree

pytestmark = pytest.mark.phase0
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def runtime_config(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in ("settings", "tools", "privacy"):
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            config_dir / f"{name}.yaml",
        )
    root = tmp_path / "Jarvis"
    create_tree(root)
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: (
            document["paths"].__setitem__("data_root", str(root)),
            document["memory"].__setitem__("summarize_on_exit", False),
        ),
    )
    return config_dir


def _mutate_yaml(path: Path, mutation: Callable[[dict[str, Any]], None]) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    mutation(document)
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _events(config_dir: Path) -> list[dict[str, Any]]:
    settings = yaml.safe_load((config_dir / "settings.yaml").read_text(encoding="utf-8"))
    root = Path(settings["paths"]["data_root"])
    records: list[dict[str, Any]] = []
    for path in sorted((root / "logs").glob("events-*.jsonl")):
        records.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return records


def test_build_assembles_config_clock_ids_events_and_secrets(runtime_config: Path) -> None:
    runtime = build(runtime_config)

    assert runtime.config.settings.schema_version == 1
    assert runtime.clock.now().tzinfo is not None
    assert runtime.ids.new("req").startswith("req_")
    assert runtime.memory_db.name == "jarvis.sqlite3"
    assert runtime.lock.acquired is False
    assert isinstance(runtime.llm, OllamaClient)
    assert isinstance(runtime.sessions, SQLiteSessionStore)
    assert isinstance(runtime.budget, BudgetGuard)


def test_application_runs_recovery_cli_and_normal_cleanup(runtime_config: Path) -> None:
    output = StringIO()
    errors = StringIO()

    exit_code = run_application(
        config_dir=runtime_config,
        input_stream=StringIO("확인\n/bye\n"),
        output_stream=output,
        error_stream=errors,
        llm=FakeLLMClient().reply("확인 응답"),
    )

    assert exit_code == 0
    assert "확인 응답" in output.getvalue()
    assert errors.getvalue() == ""
    event_types = [record["event_type"] for record in _events(runtime_config)]
    assert event_types == [
        "app.start",
        "recovery.start",
        "recovery.result",
        "recovery.start",
        "recovery.result",
        "recovery.result",
        "rag.index",
        "session.start",
        "user.input",
        "memory.search",
        "session.end",
        "app.stop",
    ]
    runtime = build(runtime_config)
    with runtime.lock:
        assert runtime.lock.acquired


def test_python_module_entrypoint_runs_once(runtime_config: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app",
            "--config-dir",
            str(runtime_config),
            "--once",
            "/help",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "사용 가능한 명령" in result.stdout
    assert result.stderr == ""
    assert _events(runtime_config)[-1]["event_type"] == "app.stop"


def test_application_ctrl_c_still_emits_stop_with_130(runtime_config: Path) -> None:
    from tests.unit.test_cli import InterruptingInput

    exit_code = run_application(
        config_dir=runtime_config,
        input_stream=InterruptingInput(),
        output_stream=StringIO(),
        error_stream=StringIO(),
    )

    assert exit_code == ExitCode.INTERRUPTED
    assert _events(runtime_config)[-1]["payload"]["exit_code"] == 130


def test_second_application_instance_returns_one(runtime_config: Path) -> None:
    settings = yaml.safe_load((runtime_config / "settings.yaml").read_text(encoding="utf-8"))
    lock_path = Path(settings["paths"]["data_root"]) / "state" / "jarvis.lock"
    errors = StringIO()

    with SingleInstanceLock(lock_path):
        exit_code = run_application(
            config_dir=runtime_config,
            input_stream=StringIO(),
            output_stream=StringIO(),
            error_stream=errors,
        )

    assert exit_code == 1
    assert "이미 실행 중" in errors.getvalue()


@pytest.mark.parametrize("dev_mode", [False, True])
def test_stack_trace_is_visible_only_in_dev_mode(
    runtime_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    dev_mode: bool,
) -> None:
    _mutate_yaml(
        runtime_config / "settings.yaml",
        lambda document: document.__setitem__("dev_mode", dev_mode),
    )

    def fail_recovery(data_root: Path, events: object) -> None:
        del data_root, events
        raise RuntimeError("internal diagnostic")

    monkeypatch.setattr("app.wiring.recover_startup", fail_recovery)
    errors = StringIO()

    exit_code = run_application(
        config_dir=runtime_config,
        input_stream=StringIO(),
        output_stream=StringIO(),
        error_stream=errors,
    )

    assert exit_code == 1
    assert ("Traceback" in errors.getvalue()) is dev_mode
    assert "internal diagnostic" not in errors.getvalue() or dev_mode

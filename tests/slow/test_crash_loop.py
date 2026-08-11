"""Abrupt child-process exits must never lose the flushed user input."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.bootstrap import create_tree

pytestmark = [pytest.mark.phase1, pytest.mark.slow, pytest.mark.timeout(900)]
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _prepare_config(root: Path) -> Path:
    config_dir = root / "config-source"
    config_dir.mkdir(parents=True)
    for name in ("settings", "tools", "privacy"):
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            config_dir / f"{name}.yaml",
        )
    data_root = root / "Jarvis"
    create_tree(data_root)
    settings_path = config_dir / "settings.yaml"
    document: dict[str, Any] = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    document["dev_mode"] = True
    document["paths"]["data_root"] = str(data_root)
    document["memory"]["checkpoint_every_turns"] = 1
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return config_dir


@pytest.mark.parametrize(
    "kill_after",
    ["user.input", "llm.request", "llm.response", "memory.write", "session.checkpoint"],
)
def test_no_input_loss_on_kill(tmp_path: Path, kill_after: str) -> None:
    for iteration in range(4):
        run_root = tmp_path / f"{kill_after.replace('.', '-')}-{iteration}"
        config_dir = _prepare_config(run_root)
        text = f"질문-{kill_after}-{iteration}"
        environment = os.environ.copy()
        environment.update(
            {
                "JARVIS_TEST_KILL_AFTER": kill_after,
                "JARVIS_LLM": "fake",
            }
        )

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "app",
                "--config-dir",
                str(config_dir),
                "--once",
                text,
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        assert result.returncode == 97, result.stderr
        raw_files = list((run_root / "Jarvis" / "memory" / "raw").glob("*.jsonl"))
        assert len(raw_files) == 1
        records = [
            json.loads(line)
            for line in raw_files[0].read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert any(record["role"] == "user" and record["content"] == text for record in records)

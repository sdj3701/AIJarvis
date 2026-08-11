"""Shared pytest fixtures for Jarvis tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.helpers.phase4_app import (
    REPOSITORY_ROOT,
    Phase4App,
    build_phase4_app,
    phase4_app,
)
from tests.helpers.phase5_app import Phase5App, build_phase5_app, phase5_app

__all__ = [
    "REPOSITORY_ROOT",
    "Phase4App",
    "Phase5App",
    "build_phase4_app",
    "build_phase5_app",
    "phase4_app",
    "phase5_app",
]


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Phase 3-style config directory with data_root outside AppData deny_paths."""
    destination = tmp_path / "config"
    destination.mkdir()
    for name in ("settings", "tools", "privacy"):
        source = REPOSITORY_ROOT / "config" / f"{name}.example.yaml"
        dest = destination / f"{name}.yaml"
        if name == "tools":
            document = yaml.safe_load(source.read_text(encoding="utf-8"))
            document["sandbox"]["deny_paths"] = [
                "C:\\Windows",
                "C:\\Program Files",
                "C:\\Program Files (x86)",
            ]
            dest.write_text(
                yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        else:
            dest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    data_root = tmp_path / "Jarvis"
    data_root.mkdir(parents=True, exist_ok=True)
    settings_path = destination / "settings.yaml"
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    document["paths"]["data_root"] = str(data_root)
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return destination

"""Smoke tests for the initial project skeleton."""

from pathlib import Path

import pytest

import app
from app.config.defaults import DEFAULT_CONFIG_DIR, DEFAULT_DATA_ROOT, PROTOTYPE_DATA_ROOT


@pytest.mark.phase0
def test_package_is_importable() -> None:
    """The source package is available to the test runner."""
    assert app.__version__ == "0.0.0"


@pytest.mark.phase0
def test_rebuild_data_is_isolated_from_prototype() -> None:
    """The rebuild must never use the prototype's operational root by default."""
    assert Path(r"D:\Jarvis") == PROTOTYPE_DATA_ROOT
    assert Path(r"D:\Jarvis-v2-dev") == DEFAULT_DATA_ROOT
    assert DEFAULT_DATA_ROOT != PROTOTYPE_DATA_ROOT
    assert DEFAULT_CONFIG_DIR == DEFAULT_DATA_ROOT / "config"

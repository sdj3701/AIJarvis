"""Smoke tests for the initial project skeleton."""

import pytest

import app


@pytest.mark.phase0
def test_package_is_importable() -> None:
    """The source package is available to the test runner."""
    assert app.__version__ == "0.0.0"

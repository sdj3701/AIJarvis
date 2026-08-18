"""Smoke tests for the Phase 0 project skeleton and quality tools."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import app
from app.config.defaults import DEFAULT_CONFIG_DIR, DEFAULT_DATA_ROOT, PROTOTYPE_DATA_ROOT

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PHASE0_RUNTIME = frozenset({"keyring", "pydantic", "python-ulid", "PyYAML"})
LATER_PHASE_LOCK_PACKAGES = frozenset(
    {
        "faster-whisper",
        "vosk",
        "sounddevice",
        "webrtcvad-wheels",
        "ddgs",
    }
)
REQUIRED_PYTEST_MARKERS = (
    "phase0",
    "phase1",
    "phase2",
    "phase3",
    "phase4",
    "phase5",
    "phase6",
    "phase7",
    "phase8",
    "security",
    "slow",
    "needs_admin",
    "needs_gpu",
    "allow_network",
)


def _requirement_name(spec: str) -> str:
    return re.split(r"[<>=\[]", spec, maxsplit=1)[0].strip()


def _lock_packages(text: str) -> dict[str, int]:
    packages: dict[str, int] = {}
    current: str | None = None
    hashes = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--hash="):
            hashes += 1
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)==", line)
        if match is None:
            continue
        if current is not None:
            packages[current] = hashes
        current = match.group(1).lower()
        hashes = 0
    if current is not None:
        packages[current] = hashes
    return packages


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


@pytest.mark.phase0
def test_pyproject_declares_phase0_quality_tools() -> None:
    """Phase 0 pins the interpreter floor, runtime deps, and quality-tool config."""
    document = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert document["project"]["requires-python"] == ">=3.11"
    runtime = {_requirement_name(item) for item in document["project"]["dependencies"]}
    assert runtime == PHASE0_RUNTIME
    markers = "\n".join(document["tool"]["pytest"]["ini_options"]["markers"])
    for marker in REQUIRED_PYTEST_MARKERS:
        assert f"{marker}:" in markers
    assert document["tool"]["ruff"]["target-version"] == "py311"
    assert document["tool"]["mypy"]["python_version"] == "3.11"
    assert document["tool"]["mypy"]["strict"] is True
    assert document["tool"]["mypy"]["files"] == ["app"]


@pytest.mark.phase0
def test_lockfile_pins_hashed_phase0_packages() -> None:
    """The lockfile is the install pin: exact versions, hashes, no later-phase extras."""
    packages = _lock_packages((REPOSITORY_ROOT / "requirements.lock").read_text(encoding="utf-8"))
    assert packages, "requirements.lock must pin at least one package"
    assert all(count >= 1 for count in packages.values())
    assert LATER_PHASE_LOCK_PACKAGES.isdisjoint(packages)
    for name in ("pydantic", "pyyaml", "keyring", "python-ulid", "pytest", "ruff", "mypy"):
        assert name in packages


@pytest.mark.phase0
def test_gitignore_hides_secrets_and_keeps_gate_evidence() -> None:
    """Local env, secrets, caches, and data copies stay private; gate JSON stays tracked."""
    text = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
    patterns = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    for required in (".venv/", ".env", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/"):
        assert required in patterns
    assert "/Jarvis-v2-dev/" in patterns
    assert not any(
        pattern.rstrip("/") in {"artifacts", "artifacts/gates"}
        or pattern in {"/artifacts/", "/artifacts/gates/", "artifacts/", "artifacts/gates/"}
        for pattern in patterns
    )
    assert "artifacts/gates" in text

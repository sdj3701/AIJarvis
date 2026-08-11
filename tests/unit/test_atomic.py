from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.atomic import write_atomic


def test_write_atomic_flushes_before_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "settings.json"
    target.write_bytes(b"old")
    calls: list[str] = []
    original_fsync = os.fsync
    original_replace = os.replace

    def recording_fsync(descriptor: int) -> None:
        calls.append("fsync")
        original_fsync(descriptor)

    def recording_replace(source: Path, destination: Path) -> None:
        calls.append("replace")
        original_replace(source, destination)

    monkeypatch.setattr("app.core.atomic.os.fsync", recording_fsync)
    monkeypatch.setattr("app.core.atomic.os.replace", recording_replace)

    write_atomic(target, b"new")

    assert target.read_bytes() == b"new"
    assert calls[:2] == ["fsync", "replace"]
    assert not target.with_suffix(".json.tmp").exists()


def test_write_atomic_leaves_recoverable_temp_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "state.json"
    target.write_bytes(b"old")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated")

    monkeypatch.setattr("app.core.atomic.os.replace", fail_replace)

    with pytest.raises(OSError, match="simulated"):
        write_atomic(target, b"new")

    assert target.read_bytes() == b"old"
    assert target.with_suffix(".json.tmp").read_bytes() == b"new"

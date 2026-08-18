"""Crash-safe replacement of complete files.

Partial-file quarantine on startup lives in ``app.core.recovery``.
"""

from __future__ import annotations

import os
from pathlib import Path


def write_atomic(path: Path, data: bytes) -> None:
    """Write bytes through a durable temporary file and atomically replace the target."""
    target = Path(path)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, target)
    _fsync_dir(target.parent)


def _fsync_dir(directory: Path) -> None:
    """Persist the directory entry where supported; Windows has no equivalent."""
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

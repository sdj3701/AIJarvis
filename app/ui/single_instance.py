"""Windows process-wide single-instance lock."""

from __future__ import annotations

import msvcrt
import os
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

from app.core.errors import JarvisError


class AlreadyRunningError(JarvisError):
    """Another Jarvis process owns the state lock."""


class SingleInstanceLock:
    """Hold an exclusive byte-range lock for the lifetime of the application."""

    def __init__(self, lock_path: Path) -> None:
        self._path = Path(lock_path)
        self._file: BinaryIO | None = None

    @property
    def acquired(self) -> bool:
        return self._file is not None

    def acquire(self) -> None:
        """Take a non-blocking byte lock so a second process fails immediately."""
        if self._file is not None:
            raise RuntimeError("single-instance lock is already acquired")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock_file = self._path.open("a+b")
        except OSError as error:
            raise JarvisError(
                "단일 인스턴스 잠금 파일을 열 수 없습니다.",
                {"error_type": type(error).__name__},
            ) from error

        try:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            lock_file.close()
            raise AlreadyRunningError(
                "Jarvis가 이미 실행 중입니다.", {"lock_file": self._path.name}
            ) from error
        self._file = lock_file

    def release(self) -> None:
        if self._file is None:
            return
        lock_file = self._file
        self._file = None
        try:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            lock_file.close()

    def __enter__(self) -> SingleInstanceLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()

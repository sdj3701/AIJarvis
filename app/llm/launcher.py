"""Ollama process launcher and healthcheck manager for auto-launch and self-healing."""

from __future__ import annotations

import subprocess
import time
from typing import Protocol
from urllib.request import Request, urlopen

from app.config.models import OLLAMA_BASE_URL
from app.core.errors import LLMUnavailable


class ProcessSpawner(Protocol):
    def spawn(self, command: list[str]) -> None: ...


class DefaultProcessSpawner:
    def spawn(self, command: list[str]) -> None:
        subprocess.Popen(
            command,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )


class OllamaLauncher:
    """Ensure Ollama server is running on loopback, auto-launching if down."""

    def __init__(
        self,
        *,
        base_url: str = OLLAMA_BASE_URL,
        binary_path: str = "ollama",
        startup_timeout_s: float = 30.0,
        poll_interval_s: float = 0.5,
        spawner: ProcessSpawner | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._binary = binary_path
        self._timeout = startup_timeout_s
        self._poll_interval = poll_interval_s
        self._spawner = spawner or DefaultProcessSpawner()

    def is_healthy(self, *, timeout_s: float = 1.5) -> bool:
        """Check if Ollama server responds with 200 OK on /api/tags."""
        req = Request(f"{self._base_url}/api/tags", headers={"Accept": "application/json"})
        try:
            with urlopen(req, timeout=timeout_s) as resp:
                return resp.status == 200
        except Exception:
            return False

    def ensure_running(self) -> bool:
        """Ensure Ollama is running. If not, auto-launch and wait for healthcheck."""
        if self.is_healthy():
            return True

        try:
            self._spawner.spawn([self._binary, "serve"])
        except OSError as error:
            raise LLMUnavailable(
                f"Ollama 실행 파일({self._binary})을 실행할 수 없습니다. 설치 여부를 확인하세요.",
                {"binary": self._binary, "error": str(error)},
            ) from error

        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            time.sleep(self._poll_interval)
            if self.is_healthy():
                return True

        raise LLMUnavailable(
            f"Ollama를 자동 실행했으나 {self._timeout}초 내에 응답하지 않았습니다.",
            {"timeout_s": self._timeout, "base_url": self._base_url},
        )

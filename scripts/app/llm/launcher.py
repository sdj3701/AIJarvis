# 파이썬 공부 | scripts/app/llm/launcher.py
# Ollama 프로세스를 실행하고 응답 가능한 상태인지 확인합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Ollama process launcher and healthcheck manager for auto-launch and self-healing."""

from __future__ import annotations

import subprocess
import time
from typing import Protocol
from urllib.request import Request, urlopen

from app.config.models import OLLAMA_BASE_URL
from app.core.errors import LLMUnavailable


# ProcessSpawner: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class ProcessSpawner(Protocol):
    # spawn(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: command.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def spawn(self, command: list[str]) -> None: ...


# DefaultProcessSpawner: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class DefaultProcessSpawner:
    # spawn(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: command.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def spawn(self, command: list[str]) -> None:
        # subprocess.Popen()을 호출해 작업을 수행합니다.
        subprocess.Popen(
            command,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )


# OllamaLauncher: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class OllamaLauncher:
    """Ensure Ollama server is running on loopback, auto-launching if down."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: base_url, binary_path, startup_timeout_s, poll_interval_s, spawner.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        *,
        base_url: str = OLLAMA_BASE_URL,
        binary_path: str = "ollama",
        startup_timeout_s: float = 30.0,
        poll_interval_s: float = 0.5,
        spawner: ProcessSpawner | None = None,
    ) -> None:
        # base_url.rstrip()의 반환값을 self._base_url에 대입합니다.
        self._base_url = base_url.rstrip("/")
        # 오른쪽 식을 계산한 값을 self._binary에 대입합니다.
        self._binary = binary_path
        # 오른쪽 식을 계산한 값을 self._timeout에 대입합니다.
        self._timeout = startup_timeout_s
        # 오른쪽 식을 계산한 값을 self._poll_interval에 대입합니다.
        self._poll_interval = poll_interval_s
        # 오른쪽 식을 계산한 값을 self._spawner에 대입합니다.
        self._spawner = spawner or DefaultProcessSpawner()

    # is_healthy(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: timeout_s.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 참/거짓(bool).
    def is_healthy(self, *, timeout_s: float = 1.5) -> bool:
        """Check if Ollama server responds with 200 OK on /api/tags."""
        # Request()의 반환값을 req에 대입합니다.
        req = Request(f"{self._base_url}/api/tags", headers={"Accept": "application/json"})
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with urlopen(req, timeout=timeout_s) as resp:
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return bool(resp.status == 200)
        # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except Exception:
            # False을 반환하고 이 함수의 실행을 끝냅니다.
            return False

    # ensure_running(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 참/거짓(bool).
    def ensure_running(self) -> bool:
        """Ensure Ollama is running. If not, auto-launch and wait for healthcheck."""
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.is_healthy().
        if self.is_healthy():
            # True을 반환하고 이 함수의 실행을 끝냅니다.
            return True

        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # self._spawner.spawn()을 호출해 작업을 수행합니다.
            self._spawner.spawn([self._binary, "serve"])
        # OSError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except OSError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMUnavailable(
                f"Ollama 실행 파일({self._binary})을 실행할 수 없습니다. 설치 여부를 확인하세요.",
                {"binary": self._binary, "error": str(error)},
            ) from error

        # 오른쪽 식을 계산한 값을 deadline에 대입합니다.
        deadline = time.monotonic() + self._timeout
        # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
        while time.monotonic() < deadline:
            # 지정한 시간만큼 현재 실행을 기다리게 합니다.
            time.sleep(self._poll_interval)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.is_healthy().
            if self.is_healthy():
                # True을 반환하고 이 함수의 실행을 끝냅니다.
                return True

        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMUnavailable(
            f"Ollama를 자동 실행했으나 {self._timeout}초 내에 응답하지 않았습니다.",
            {"timeout_s": self._timeout, "base_url": self._base_url},
        )

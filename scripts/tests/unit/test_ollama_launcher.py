# 파이썬 공부 | scripts/tests/unit/test_ollama_launcher.py
# ollama_launcher 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Unit tests for Ollama auto-launcher and self-healing integration."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.config.models import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL_DIGEST,
    ContextSettings,
    LLMSettings,
    ModelPricing,
)
from app.core.context import RequestContext
from app.core.errors import LLMUnavailable
from app.llm.base import Message
from app.llm.launcher import OllamaLauncher
from app.llm.ollama_client import OllamaClient, OllamaConnectionFailure, OllamaTransport


# MockSpawner: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class MockSpawner:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # self.spawned_commands에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.spawned_commands: list[list[str]] = []

    # spawn(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: command.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def spawn(self, command: list[str]) -> None:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.spawned_commands.append(command)


# pytest가 test_launcher_already_healthy_does_not_spawn()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_launcher_already_healthy_does_not_spawn() -> None:
    # MockSpawner()의 반환값을 spawner에 대입합니다.
    spawner = MockSpawner()
    # OllamaLauncher()의 반환값을 launcher에 대입합니다.
    launcher = OllamaLauncher(binary_path="ollama", spawner=spawner)

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch.object(launcher, "is_healthy", return_value=True):
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert launcher.ensure_running() is True
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert len(spawner.spawned_commands) == 0


# pytest가 test_launcher_spawns_and_waits_for_health()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_launcher_spawns_and_waits_for_health() -> None:
    # MockSpawner()의 반환값을 spawner에 대입합니다.
    spawner = MockSpawner()
    # OllamaLauncher()의 반환값을 launcher에 대입합니다.
    launcher = OllamaLauncher(binary_path="ollama", startup_timeout_s=2.0, poll_interval_s=0.05, spawner=spawner)

    # First check: False, second check (after spawn): True
    # health_states에 리스트(순서가 있고 수정 가능)을 대입합니다.
    health_states = [False, True]

    # mock_health(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # *args는 추가 위치 인자를 튜플로 모읍니다.
    # **kwargs는 추가 이름 인자를 딕셔너리로 모읍니다.
    # 반환 타입 힌트: 참/거짓(bool).
    def mock_health(*args, **kwargs) -> bool:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        return health_states.pop(0) if health_states else True

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch.object(launcher, "is_healthy", side_effect=mock_health):
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert launcher.ensure_running() is True
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert spawner.spawned_commands == [["ollama", "serve"]]


# pytest가 test_launcher_timeout_raises_llm_unavailable()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_launcher_timeout_raises_llm_unavailable() -> None:
    # MockSpawner()의 반환값을 spawner에 대입합니다.
    spawner = MockSpawner()
    # OllamaLauncher()의 반환값을 launcher에 대입합니다.
    launcher = OllamaLauncher(binary_path="ollama", startup_timeout_s=0.2, poll_interval_s=0.05, spawner=spawner)

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch.object(launcher, "is_healthy", return_value=False):
        # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
        with pytest.raises(LLMUnavailable, match="응답하지 않았습니다"):
            # launcher.ensure_running()을 호출해 작업을 수행합니다.
            launcher.ensure_running()
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert spawner.spawned_commands == [["ollama", "serve"]]


# pytest가 test_ollama_client_auto_launches_on_connection_failure()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_ollama_client_auto_launches_on_connection_failure() -> None:
    # LLMSettings()의 반환값을 settings에 대입합니다.
    settings = LLMSettings(
        provider="ollama",
        base_url=OLLAMA_BASE_URL,
        model="qwen3.5:9b",
        model_digest=OLLAMA_MODEL_DIGEST,
        temperature=0.2,
        max_output_tokens=2048,
        timeout_s=5.0,
        max_retries=1,
        backoff_base_s=0.1,
        backoff_max_s=0.5,
        think=False,
        local_only=True,
        runtime_context_tokens=16384,
        pricing={
            "qwen3.5:9b": ModelPricing(
                input_per_1k=Decimal("0.0"),
                output_per_1k=Decimal("0.0"),
            )
        },
        context=ContextSettings(
            max_input_tokens=14336,
            reserve_output_tokens=2048,
            memory_share=0.25,
            history_share=0.5,
            keep_recent_turns=3,
        ),
        retry_on=["timeout", "connection_error", "server_error"],
    )

    # MagicMock()의 반환값을 mock_transport에 대입합니다.
    mock_transport = MagicMock(spec=OllamaTransport)
    # First call: connection failure, second call (after auto-launch): success
    # mock_transport.request_json.side_effect에 리스트(순서가 있고 수정 가능)을 대입합니다.
    mock_transport.request_json.side_effect = [
        OllamaConnectionFailure("Connection refused"),
        {
            "done": True,
            "done_reason": "stop",
            "model": "qwen3.5:9b",
            "message": {"role": "assistant", "content": "안녕하세요! 무엇을 도와드릴까요?"},
            "prompt_eval_count": 10,
            "eval_count": 15,
            "total_duration": 100_000_000,
        },
    ]

    # MagicMock()의 반환값을 mock_launcher에 대입합니다.
    mock_launcher = MagicMock(spec=OllamaLauncher)
    # mock_launcher.ensure_running.return_value을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    mock_launcher.ensure_running.return_value = True

    # OllamaClient()의 반환값을 client에 대입합니다.
    client = OllamaClient(settings, transport=mock_transport, launcher=mock_launcher)
    # MagicMock()의 반환값을 ctx에 대입합니다.
    ctx = MagicMock(spec=RequestContext)
    # ctx.cancel.raise_if_cancelled.return_value을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    ctx.cancel.raise_if_cancelled.return_value = None
    # ctx.clock.monotonic_ms.return_value에 숫자 등 고정된 값을 대입합니다.
    ctx.clock.monotonic_ms.return_value = 1000

    # client.complete()의 반환값을 response에 대입합니다.
    response = client.complete(
        messages=[Message("user", "안녕")],
        timeout_s=5.0,
        ctx=ctx,
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response.text == "안녕하세요! 무엇을 도와드릴까요?"
    # mock_launcher.ensure_running.assert_called_once()을 호출해 작업을 수행합니다.
    mock_launcher.ensure_running.assert_called_once()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert mock_transport.request_json.call_count == 2

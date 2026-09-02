"""Unit tests for Ollama auto-launcher and self-healing integration."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.config.models import LLMContextSettings, LLMSettings, ModelPricing
from app.core.context import RequestContext
from app.core.errors import LLMUnavailable
from app.llm.base import Message
from app.llm.launcher import OllamaLauncher
from app.llm.ollama_client import OllamaClient, OllamaConnectionFailure, OllamaTransport


class MockSpawner:
    def __init__(self) -> None:
        self.spawned_commands: list[list[str]] = []

    def spawn(self, command: list[str]) -> None:
        self.spawned_commands.append(command)


def test_launcher_already_healthy_does_not_spawn() -> None:
    spawner = MockSpawner()
    launcher = OllamaLauncher(binary_path="ollama", spawner=spawner)

    with patch.object(launcher, "is_healthy", return_value=True):
        assert launcher.ensure_running() is True
        assert len(spawner.spawned_commands) == 0


def test_launcher_spawns_and_waits_for_health() -> None:
    spawner = MockSpawner()
    launcher = OllamaLauncher(binary_path="ollama", startup_timeout_s=2.0, poll_interval_s=0.05, spawner=spawner)

    # First check: False, second check (after spawn): True
    health_states = [False, True]

    def mock_health(*args, **kwargs) -> bool:
        return health_states.pop(0) if health_states else True

    with patch.object(launcher, "is_healthy", side_effect=mock_health):
        assert launcher.ensure_running() is True
        assert spawner.spawned_commands == [["ollama", "serve"]]


def test_launcher_timeout_raises_llm_unavailable() -> None:
    spawner = MockSpawner()
    launcher = OllamaLauncher(binary_path="ollama", startup_timeout_s=0.2, poll_interval_s=0.05, spawner=spawner)

    with patch.object(launcher, "is_healthy", return_value=False):
        with pytest.raises(LLMUnavailable, match="응답하지 않았습니다"):
            launcher.ensure_running()
        assert spawner.spawned_commands == [["ollama", "serve"]]


def test_ollama_client_auto_launches_on_connection_failure() -> None:
    settings = LLMSettings(
        provider="ollama",
        model="qwen3.5:9b",
        model_digest="sha256:d005modeldigestplaceholder1234567890abcdef1234567890abcdef12345678",
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
        context=LLMContextSettings(
            max_input_tokens=14336,
            reserve_output_tokens=2048,
            memory_share=0.25,
            history_reserve_tokens=4096,
        ),
        retry_on=["timeout", "connection_error", "server_error"],
    )

    mock_transport = MagicMock(spec=OllamaTransport)
    # First call: connection failure, second call (after auto-launch): success
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

    mock_launcher = MagicMock(spec=OllamaLauncher)
    mock_launcher.ensure_running.return_value = True

    client = OllamaClient(settings, transport=mock_transport, launcher=mock_launcher)
    ctx = MagicMock(spec=RequestContext)
    ctx.cancel.raise_if_cancelled.return_value = None
    ctx.clock.monotonic_ms.return_value = 1000

    response = client.complete(
        messages=[Message("user", "안녕")],
        timeout_s=5.0,
        ctx=ctx,
    )

    assert response.text == "안녕하세요! 무엇을 도와드릴까요?"
    mock_launcher.ensure_running.assert_called_once()
    assert mock_transport.request_json.call_count == 2

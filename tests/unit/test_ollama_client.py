"""Unit tests for the strict local-only Ollama adapter."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError

import pytest
import yaml

from app.config.models import LLMSettings, Settings
from app.core.context import RequestContext
from app.core.errors import LLMBadResponse, LLMTimeout, LLMUnavailable
from app.llm.base import Message
from app.llm.ollama_client import (
    OllamaClient,
    OllamaConnectionFailure,
    OllamaHTTPFailure,
    OllamaTimeoutFailure,
    UrllibOllamaTransport,
)
from tests.fakes.clock import FixedRandom, FrozenClock, ImmediateSleeper

pytestmark = pytest.mark.phase1
KST = timezone(timedelta(hours=9), name="KST")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class ScriptedTransport:
    def __init__(self, *script: Mapping[str, Any] | Exception) -> None:
        self.script = list(script)
        self.requests: list[tuple[str, str, Mapping[str, Any] | None, float]] = []

    def request_json(
        self,
        method: str,
        url: str,
        payload: Mapping[str, Any] | None,
        *,
        timeout_s: float,
    ) -> Mapping[str, Any]:
        self.requests.append((method, url, payload, timeout_s))
        if not self.script:
            raise AssertionError("unexpected Ollama transport call")
        result = self.script.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class RecordingEvents:
    def __init__(self) -> None:
        self.records: list[tuple[str, Mapping[str, Any]]] = []

    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        self.records.append((event_type, payload))


class ActiveCancellation:
    def __init__(self, *, cancelled: bool = False) -> None:
        self.cancelled = cancelled

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise InterruptedError("cancelled")


class FakeHTTPResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self, limit: int) -> bytes:
        del limit
        return self.body


def _llm_settings() -> LLMSettings:
    document = yaml.safe_load(
        (REPOSITORY_ROOT / "config" / "settings.example.yaml").read_text(encoding="utf-8")
    )
    return Settings.model_validate(document).llm


def _context(
    *,
    events: RecordingEvents | None = None,
    sleeper: ImmediateSleeper | None = None,
    cancelled: bool = False,
) -> RequestContext:
    current = datetime(2026, 8, 11, 12, 0, tzinfo=KST)
    value = type(
        "OllamaTestContext",
        (),
        {
            "cancel": ActiveCancellation(cancelled=cancelled),
            "events": events or RecordingEvents(),
            "clock": FrozenClock(current),
            "random": FixedRandom(0.0),
            "sleeper": sleeper or ImmediateSleeper(),
        },
    )()
    return cast(RequestContext, value)


def _chat_response(**updates: Any) -> dict[str, Any]:
    response: dict[str, Any] = {
        "model": "qwen3.5:9b",
        "message": {"role": "assistant", "content": "네, 준비되었습니다."},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 12,
        "eval_count": 7,
        "total_duration": 42_000_000,
    }
    response.update(updates)
    return response


def _tags_response(*, digest: str | None = None) -> dict[str, Any]:
    selected_digest = digest or _llm_settings().model_digest
    return {
        "models": [
            {
                "name": "qwen3.5:9b",
                "digest": selected_digest,
                "size": 6_594_474_711,
                "details": {
                    "parameter_size": "9.7B",
                    "quantization_level": "Q4_K_M",
                },
            }
        ]
    }


def test_urllib_transport_sends_utf8_json_and_parses_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[Any, float]] = []

    def fake_urlopen(request: Any, *, timeout: float) -> FakeHTTPResponse:
        captured.append((request, timeout))
        return FakeHTTPResponse('{"answer":"안녕"}'.encode())

    monkeypatch.setattr("app.llm.ollama_client.urlopen", fake_urlopen)
    response = UrllibOllamaTransport().request_json(
        "POST",
        "http://127.0.0.1:11434/api/chat",
        {"text": "한글"},
        timeout_s=2.5,
    )

    assert response == {"answer": "안녕"}
    request, timeout = captured[0]
    assert timeout == 2.5
    assert request.full_url == "http://127.0.0.1:11434/api/chat"
    assert request.method == "POST"
    assert request.data.decode() == '{"text":"한글"}'
    assert request.get_header("Content-type") == "application/json; charset=utf-8"


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (HTTPError("http://local", 503, "error", None, None), OllamaHTTPFailure),
        (TimeoutError(), OllamaTimeoutFailure),
        (URLError(TimeoutError()), OllamaTimeoutFailure),
        (URLError("refused"), OllamaConnectionFailure),
        (OSError("refused"), OllamaConnectionFailure),
    ],
)
def test_urllib_transport_maps_network_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected: type[Exception],
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise failure

    monkeypatch.setattr("app.llm.ollama_client.urlopen", fail)
    with pytest.raises(expected):
        UrllibOllamaTransport().request_json(
            "GET",
            "http://127.0.0.1:11434/api/tags",
            None,
            timeout_s=1,
        )


@pytest.mark.parametrize("body", [b"not-json", b"[]"])
def test_urllib_transport_rejects_invalid_json_shapes(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    monkeypatch.setattr(
        "app.llm.ollama_client.urlopen",
        lambda *args, **kwargs: FakeHTTPResponse(body),
    )
    with pytest.raises(LLMBadResponse):
        UrllibOllamaTransport().request_json(
            "GET",
            "http://127.0.0.1:11434/api/tags",
            None,
            timeout_s=1,
        )


def test_urllib_transport_rejects_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.llm.ollama_client._MAX_RESPONSE_BYTES", 4)
    monkeypatch.setattr(
        "app.llm.ollama_client.urlopen",
        lambda *args, **kwargs: FakeHTTPResponse(b"12345"),
    )
    with pytest.raises(LLMBadResponse, match="크기"):
        UrllibOllamaTransport().request_json(
            "GET",
            "http://127.0.0.1:11434/api/tags",
            None,
            timeout_s=1,
        )


def test_verify_model_checks_exact_tag_and_digest() -> None:
    transport = ScriptedTransport(_tags_response())
    info = OllamaClient(_llm_settings(), transport=transport).verify_model(timeout_s=3)

    assert info.name == "qwen3.5:9b"
    assert info.quantization == "Q4_K_M"
    assert info.size_bytes == 6_594_474_711
    assert transport.requests == [
        ("GET", "http://127.0.0.1:11434/api/tags", None, 3)
    ]


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (OllamaTimeoutFailure(), LLMTimeout),
        (OllamaConnectionFailure(), LLMUnavailable),
        (OllamaHTTPFailure(500), LLMUnavailable),
    ],
)
def test_verify_model_maps_transport_failures(
    failure: Exception,
    expected: type[Exception],
) -> None:
    with pytest.raises(expected):
        OllamaClient(_llm_settings(), transport=ScriptedTransport(failure)).verify_model()


@pytest.mark.parametrize(
    "response",
    [
        {"models": []},
        _tags_response(digest="0" * 64),
        {"models": "invalid"},
        {"models": [{"name": "qwen3.5:9b", "digest": _llm_settings().model_digest}]},
    ],
)
def test_verify_model_rejects_missing_changed_or_malformed_model(
    response: Mapping[str, Any],
) -> None:
    client = OllamaClient(_llm_settings(), transport=ScriptedTransport(response))

    with pytest.raises((LLMUnavailable, LLMBadResponse)):
        client.verify_model()


def test_complete_maps_request_response_usage_and_events() -> None:
    transport = ScriptedTransport(_chat_response())
    events = RecordingEvents()
    client = OllamaClient(_llm_settings(), transport=transport)
    messages = [
        Message("system", "<!-- version: 1 -->\n한국어로 답하세요."),
        Message("user", "준비됐나요?"),
    ]

    response = client.complete(messages=messages, timeout_s=30, ctx=_context(events=events))

    assert response.text == "네, 준비되었습니다."
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 7
    assert response.usage.cost_usd == 0
    assert response.usage.latency_ms == 42
    method, url, payload, timeout_s = transport.requests[0]
    assert (method, url, timeout_s) == ("POST", "http://127.0.0.1:11434/api/chat", 30)
    assert payload is not None
    assert payload["model"] == "qwen3.5:9b"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["options"] == {
        "temperature": 0.3,
        "num_predict": 2000,
        "num_ctx": 16384,
    }
    assert [event_type for event_type, _ in events.records] == ["llm.request", "llm.response"]
    assert events.records[0][1]["prompt_version"] == "1"
    assert events.records[1][1]["cost_usd"] == "0.00"


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (OllamaTimeoutFailure(), "timeout"),
        (OllamaConnectionFailure(), "connection_error"),
        (OllamaHTTPFailure(503), "server_error"),
    ],
)
def test_retryable_failures_back_off_then_succeed(failure: Exception, reason: str) -> None:
    transport = ScriptedTransport(failure, _chat_response())
    sleeper = ImmediateSleeper()
    events = RecordingEvents()
    response = OllamaClient(_llm_settings(), transport=transport).complete(
        messages=[Message("user", "재시도")],
        timeout_s=5,
        ctx=_context(events=events, sleeper=sleeper),
    )

    assert response.text
    assert sleeper.durations == [0.5]
    assert len(transport.requests) == 2
    retry = next(payload for event, payload in events.records if event == "llm.retry")
    assert retry == {"attempt": 1, "reason": reason, "wait_ms": 500}


def test_retry_gives_up_after_configured_max_without_real_sleep() -> None:
    transport = ScriptedTransport(*(OllamaTimeoutFailure() for _ in range(4)))
    sleeper = ImmediateSleeper()

    with pytest.raises(LLMTimeout) as captured:
        OllamaClient(_llm_settings(), transport=transport).complete(
            messages=[Message("user", "시간 초과")],
            timeout_s=1,
            ctx=_context(sleeper=sleeper),
        )

    assert captured.value.detail["attempts"] == 4
    assert sleeper.durations == [0.5, 1.0, 2.0]
    assert len(transport.requests) == 4


def test_connection_failure_gives_up_as_unavailable() -> None:
    transport = ScriptedTransport(*(OllamaConnectionFailure() for _ in range(4)))

    with pytest.raises(LLMUnavailable) as captured:
        OllamaClient(_llm_settings(), transport=transport).complete(
            messages=[Message("user", "연결 실패")],
            timeout_s=1,
            ctx=_context(),
        )

    assert captured.value.detail == {"reason": "connection_error", "attempts": 4}


def test_http_4xx_is_not_retried() -> None:
    transport = ScriptedTransport(OllamaHTTPFailure(404), _chat_response())

    with pytest.raises(LLMBadResponse) as captured:
        OllamaClient(_llm_settings(), transport=transport).complete(
            messages=[Message("user", "없는 모델")],
            timeout_s=1,
            ctx=_context(),
        )

    assert captured.value.detail == {"status": 404}
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    "response",
    [
        _chat_response(done=False),
        _chat_response(model="other"),
        _chat_response(done_reason="unknown"),
        _chat_response(prompt_eval_count=-1),
        _chat_response(message={"role": "assistant", "content": "", "tool_calls": [{"x": 1}]}),
        _chat_response(message={"role": "user", "content": "잘못된 역할"}),
        _chat_response(message={"role": "assistant", "content": ""}),
    ],
)
def test_malformed_or_unsupported_responses_are_rejected(response: Mapping[str, Any]) -> None:
    client = OllamaClient(_llm_settings(), transport=ScriptedTransport(response))

    with pytest.raises(LLMBadResponse):
        client.complete(
            messages=[Message("user", "검증")],
            timeout_s=1,
            ctx=_context(),
        )


def test_phase_one_rejects_tools_tool_messages_and_cancelled_requests() -> None:
    transport = ScriptedTransport(_chat_response())
    client = OllamaClient(_llm_settings(), transport=transport)

    with pytest.raises(LLMBadResponse, match="도구"):
        client.complete(
            messages=[Message("user", "도구")],
            tools=[{"name": "search"}],
            timeout_s=1,
            ctx=_context(),
        )
    with pytest.raises(LLMBadResponse, match="tool 역할"):
        client.complete(
            messages=[Message("tool", "결과", tool_call_id="call_1")],
            timeout_s=1,
            ctx=_context(),
        )
    with pytest.raises(InterruptedError):
        client.complete(
            messages=[Message("user", "취소")],
            timeout_s=1,
            ctx=_context(cancelled=True),
        )
    assert transport.requests == []


def test_token_estimate_is_deterministic_and_context_limit_is_enforced() -> None:
    client = OllamaClient(_llm_settings(), transport=ScriptedTransport())
    messages = [Message("system", "abcd"), Message("user", "한글")]
    assert client.count_tokens(messages) == 12

    with pytest.raises(ValueError, match="16K"):
        client.complete(
            messages=[Message("user", "가" * 50_000)],
            timeout_s=1,
            ctx=_context(),
        )


def test_empty_prompt_is_rejected_and_missing_duration_uses_clock() -> None:
    client = OllamaClient(
        _llm_settings(),
        transport=ScriptedTransport(_chat_response(total_duration=None)),
    )
    with pytest.raises(ValueError, match="메시지"):
        client.complete(messages=[], timeout_s=1, ctx=_context())

    response = client.complete(
        messages=[Message("user", "지연시간")],
        timeout_s=1,
        ctx=_context(),
        temperature=0.1,
        max_output_tokens=10,
    )
    assert response.usage.latency_ms == 0


def test_client_defensively_rejects_non_loopback_settings_copy() -> None:
    unsafe = _llm_settings().model_copy(update={"base_url": "http://example.com"})

    with pytest.raises(ValueError, match="loopback"):
        OllamaClient(unsafe)

    non_local = _llm_settings().model_copy(update={"local_only": False})
    with pytest.raises(ValueError, match="local_only"):
        OllamaClient(non_local)

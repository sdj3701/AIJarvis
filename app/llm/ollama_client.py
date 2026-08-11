"""Strict local-only Ollama chat client for the D005 model decision."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from json import JSONDecodeError
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config.models import OLLAMA_BASE_URL, LLMSettings
from app.core.context import RequestContext
from app.core.errors import LLMBadResponse, LLMTimeout, LLMUnavailable
from app.llm.base import (
    LLMResponse,
    LLMUsage,
    Message,
    ToolSpec,
    validate_request_limits,
)

_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_PROMPT_VERSION = re.compile(r"^<!--\s*version:\s*([^\s]+)\s*-->")


class OllamaHTTPFailure(Exception):
    """HTTP status returned by Ollama without retaining a possibly sensitive body."""

    def __init__(self, status: int) -> None:
        super().__init__(f"Ollama HTTP {status}")
        self.status = status


class OllamaConnectionFailure(Exception):
    """The loopback connection could not be established."""


class OllamaTimeoutFailure(Exception):
    """The loopback request exceeded its deadline."""


class OllamaTransport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        payload: Mapping[str, Any] | None,
        *,
        timeout_s: float,
    ) -> Mapping[str, Any]: ...


class UrllibOllamaTransport:
    """Small JSON transport that has no route selection or cloud fallback."""

    def request_json(
        self,
        method: str,
        url: str,
        payload: Mapping[str, Any] | None,
        *,
        timeout_s: float,
    ) -> Mapping[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout_s) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            raise OllamaHTTPFailure(error.code) from error
        except TimeoutError as error:
            raise OllamaTimeoutFailure from error
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise OllamaTimeoutFailure from error
            raise OllamaConnectionFailure from error
        except OSError as error:
            raise OllamaConnectionFailure from error

        if len(raw) > _MAX_RESPONSE_BYTES:
            raise LLMBadResponse("Ollama 응답이 허용 크기를 초과했습니다.")
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeError, JSONDecodeError) as error:
            raise LLMBadResponse("Ollama 응답 JSON이 올바르지 않습니다.") from error
        if not isinstance(parsed, dict):
            raise LLMBadResponse("Ollama 응답 최상위 값이 객체가 아닙니다.")
        return cast(dict[str, Any], parsed)


@dataclass(frozen=True, slots=True)
class OllamaModelInfo:
    name: str
    digest: str
    size_bytes: int
    parameter_size: str
    quantization: str


class OllamaClient:
    """Map Ollama's local chat API to the provider-neutral LLM contract."""

    name = "ollama"

    def __init__(
        self,
        settings: LLMSettings,
        *,
        transport: OllamaTransport | None = None,
    ) -> None:
        if settings.base_url != OLLAMA_BASE_URL:
            raise ValueError("Ollama base URL은 고정 loopback 주소여야 합니다.")
        if not settings.local_only:
            raise ValueError("Ollama 클라이언트는 local_only=true만 지원합니다.")
        self._settings = settings
        self._transport = transport or UrllibOllamaTransport()

    def verify_model(self, *, timeout_s: float = 5.0) -> OllamaModelInfo:
        """Verify the installed tag and full manifest digest before chat starts."""
        validate_request_limits(
            timeout_s=timeout_s,
            temperature=None,
            max_output_tokens=None,
        )
        try:
            response = self._transport.request_json(
                "GET",
                f"{OLLAMA_BASE_URL}/api/tags",
                None,
                timeout_s=timeout_s,
            )
        except OllamaTimeoutFailure as error:
            raise LLMTimeout("Ollama 모델 확인 시간이 초과되었습니다.") from error
        except OllamaConnectionFailure as error:
            raise LLMUnavailable(
                "Ollama에 연결할 수 없습니다. Ollama가 실행 중인지 확인하세요."
            ) from error
        except OllamaHTTPFailure as error:
            raise LLMUnavailable(
                "Ollama 모델 목록을 확인할 수 없습니다.",
                {"status": error.status},
            ) from error

        models = response.get("models")
        if not isinstance(models, list):
            raise LLMBadResponse("Ollama 모델 목록 형식이 올바르지 않습니다.")
        selected = next(
            (
                item
                for item in models
                if isinstance(item, dict) and item.get("name") == self._settings.model
            ),
            None,
        )
        if selected is None:
            raise LLMUnavailable(
                f"로컬 모델 {self._settings.model}이 없습니다. ollama pull을 실행하세요."
            )
        digest = selected.get("digest")
        if digest != self._settings.model_digest:
            raise LLMBadResponse("설치된 Ollama 모델 digest가 D005 결정과 다릅니다.")
        details = selected.get("details")
        if not isinstance(details, dict):
            raise LLMBadResponse("Ollama 모델 상세 정보 형식이 올바르지 않습니다.")
        return OllamaModelInfo(
            name=self._settings.model,
            digest=digest,
            size_bytes=_nonnegative_int(selected.get("size"), "model.size"),
            parameter_size=_required_string(details.get("parameter_size"), "parameter_size"),
            quantization=_required_string(details.get("quantization_level"), "quantization"),
        )

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        timeout_s: float,
        ctx: RequestContext,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        validate_request_limits(
            timeout_s=timeout_s,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        if not messages:
            raise ValueError("Ollama 요청에는 메시지가 하나 이상 필요합니다.")
        if tools:
            raise LLMBadResponse("Phase 1에서는 도구를 Ollama에 전달하지 않습니다.")
        if any(message.role == "tool" for message in messages):
            raise LLMBadResponse("Phase 1에서는 tool 역할 메시지를 처리하지 않습니다.")

        output_limit = max_output_tokens or self._settings.max_output_tokens
        selected_temperature = (
            self._settings.temperature if temperature is None else temperature
        )
        prompt_tokens_est = self.count_tokens(messages)
        if prompt_tokens_est + output_limit > self._settings.runtime_context_tokens:
            raise ValueError("Ollama 요청이 설정된 16K 문맥 한도를 초과합니다.")
        payload = {
            "model": self._settings.model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "stream": False,
            "think": self._settings.think,
            "options": {
                "temperature": selected_temperature,
                "num_predict": output_limit,
                "num_ctx": self._settings.runtime_context_tokens,
            },
        }
        prompt_version = _prompt_version(messages)

        for attempt in range(1, self._settings.max_retries + 2):
            ctx.cancel.raise_if_cancelled()
            ctx.events.emit(
                "llm.request",
                {
                    "model": self._settings.model,
                    "attempt": attempt,
                    "prompt_tokens_est": prompt_tokens_est,
                    "prompt_version": prompt_version,
                    "tool_count": 0,
                    "memory_record_ids": [],
                },
            )
            started_ms = ctx.clock.monotonic_ms()
            try:
                raw_response = self._transport.request_json(
                    "POST",
                    f"{OLLAMA_BASE_URL}/api/chat",
                    payload,
                    timeout_s=timeout_s,
                )
            except OllamaTimeoutFailure as error:
                self._retry_or_raise("timeout", attempt, ctx, error)
                continue
            except OllamaConnectionFailure as error:
                self._retry_or_raise("connection_error", attempt, ctx, error)
                continue
            except OllamaHTTPFailure as error:
                if 500 <= error.status <= 599:
                    self._retry_or_raise("server_error", attempt, ctx, error)
                    continue
                raise LLMBadResponse(
                    "Ollama가 요청을 거부했습니다.",
                    {"status": error.status},
                ) from error

            response = self._parse_response(raw_response, started_ms=started_ms, ctx=ctx)
            ctx.events.emit(
                "llm.response",
                {
                    "model": response.model,
                    "finish_reason": response.finish_reason,
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "cost_usd": format(response.usage.cost_usd, "f"),
                    "latency_ms": response.usage.latency_ms,
                    "tool_call_names": [],
                },
            )
            return response

        raise AssertionError("Ollama retry loop terminated unexpectedly")

    def count_tokens(self, messages: Sequence[Message]) -> int:
        """Return a conservative deterministic estimate without another HTTP call."""
        return sum(
            4 + max(1, (len(message.content.encode("utf-8")) + 2) // 3)
            for message in messages
        )

    def _retry_or_raise(
        self,
        reason: str,
        attempt: int,
        ctx: RequestContext,
        error: Exception,
    ) -> None:
        if reason not in self._settings.retry_on or attempt > self._settings.max_retries:
            if reason == "timeout":
                raise LLMTimeout(
                    "Ollama 응답 시간이 초과되었습니다.",
                    {"attempts": attempt},
                ) from error
            raise LLMUnavailable(
                "Ollama가 응답하지 않습니다. 실행 상태와 모델을 확인하세요.",
                {"reason": reason, "attempts": attempt},
            ) from error

        base_wait = min(
            self._settings.backoff_max_s,
            self._settings.backoff_base_s * (2 ** (attempt - 1)),
        )
        wait_s = min(
            self._settings.backoff_max_s,
            base_wait + ctx.random.uniform(0.0, base_wait * 0.25),
        )
        ctx.events.emit(
            "llm.retry",
            {"attempt": attempt, "reason": reason, "wait_ms": round(wait_s * 1000)},
        )
        ctx.cancel.raise_if_cancelled()
        ctx.sleeper.sleep(wait_s)

    def _parse_response(
        self,
        response: Mapping[str, Any],
        *,
        started_ms: int,
        ctx: RequestContext,
    ) -> LLMResponse:
        if response.get("done") is not True:
            raise LLMBadResponse("Ollama가 완료되지 않은 응답을 반환했습니다.")
        if response.get("model") != self._settings.model:
            raise LLMBadResponse("Ollama 응답 모델이 설정과 일치하지 않습니다.")
        message = response.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise LLMBadResponse("Ollama assistant 메시지 형식이 올바르지 않습니다.")
        if message.get("tool_calls"):
            raise LLMBadResponse("Phase 1에서는 Ollama 도구 호출 응답을 처리하지 않습니다.")
        text = _required_string(message.get("content"), "message.content")
        done_reason = response.get("done_reason")
        if done_reason not in {"stop", "length"}:
            raise LLMBadResponse("알 수 없는 Ollama 종료 사유입니다.")

        prompt_tokens = _nonnegative_int(response.get("prompt_eval_count"), "prompt_eval_count")
        completion_tokens = _nonnegative_int(response.get("eval_count"), "eval_count")
        total_duration = response.get("total_duration")
        if total_duration is None:
            latency_ms = max(0, ctx.clock.monotonic_ms() - started_ms)
        else:
            latency_ms = _nonnegative_int(total_duration, "total_duration") // 1_000_000
        pricing = self._settings.pricing[self._settings.model]
        cost = (
            Decimal(prompt_tokens) * pricing.input_per_1k
            + Decimal(completion_tokens) * pricing.output_per_1k
        ) / Decimal(1000)
        return LLMResponse(
            text=text,
            tool_calls=(),
            usage=LLMUsage(prompt_tokens, completion_tokens, cost, latency_ms),
            model=self._settings.model,
            finish_reason=done_reason,
        )


def _prompt_version(messages: Sequence[Message]) -> str:
    if messages and messages[0].role == "system":
        lines = messages[0].content.splitlines()
        if lines:
            match = _PROMPT_VERSION.match(lines[0])
            if match is not None:
                return match.group(1)
    return "unversioned"


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise LLMBadResponse(f"Ollama 응답의 {field} 값이 올바르지 않습니다.")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LLMBadResponse(f"Ollama 응답의 {field} 값이 올바르지 않습니다.")
    return value

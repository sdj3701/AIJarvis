# 파이썬 공부 | scripts/app/llm/ollama_client.py
# 로컬 Ollama 서버에 대화를 요청하고 응답을 검증합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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
    ToolCall,
    ToolSpec,
    validate_request_limits,
)
from app.llm.launcher import OllamaLauncher

# 오른쪽 식을 계산한 값을 _MAX_RESPONSE_BYTES에 대입합니다.
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
# re.compile()의 반환값을 _PROMPT_VERSION에 대입합니다.
_PROMPT_VERSION = re.compile(r"^<!--\s*version:\s*([^\s]+)\s*-->")
# re.compile()의 반환값을 _CONTROL_CHARS에 대입합니다.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f]")
# _MAX_TOOL_NAME_LENGTH에 숫자 등 고정된 값을 대입합니다.
_MAX_TOOL_NAME_LENGTH = 128


# OllamaHTTPFailure: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: Exception.
class OllamaHTTPFailure(Exception):
    """HTTP status returned by Ollama without retaining a possibly sensitive body."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: status.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, status: int) -> None:
        # super().__init__()을 호출해 작업을 수행합니다.
        super().__init__(f"Ollama HTTP {status}")
        # 오른쪽 식을 계산한 값을 self.status에 대입합니다.
        self.status = status


# OllamaConnectionFailure: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: Exception.
class OllamaConnectionFailure(Exception):
    """The loopback connection could not be established."""


# OllamaTimeoutFailure: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: Exception.
class OllamaTimeoutFailure(Exception):
    """The loopback request exceeded its deadline."""


# OllamaTransport: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class OllamaTransport(Protocol):
    # request_json(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: method, url, payload, timeout_s.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: Mapping[str, Any].
    def request_json(
        self,
        method: str,
        url: str,
        payload: Mapping[str, Any] | None,
        *,
        timeout_s: float,
    ) -> Mapping[str, Any]: ...


# UrllibOllamaTransport: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class UrllibOllamaTransport:
    """Small JSON transport that has no route selection or cloud fallback."""

    # request_json(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: method, url, payload, timeout_s.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: Mapping[str, Any].
    def request_json(
        self,
        method: str,
        url: str,
        payload: Mapping[str, Any] | None,
        *,
        timeout_s: float,
    ) -> Mapping[str, Any]:
        # body을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        body = None
        # headers에 딕셔너리(키와 값의 쌍)을 대입합니다.
        headers = {"Accept": "application/json"}
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: payload is not None.
        if payload is not None:
            # 아래 함수()의 반환값을 body에 대입합니다.
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            # headers['Content-Type']에 문자열을 대입합니다.
            headers["Content-Type"] = "application/json; charset=utf-8"
        # Request()의 반환값을 request에 대입합니다.
        request = Request(url, data=body, headers=headers, method=method)
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with urlopen(request, timeout=timeout_s) as response:
                # response.read()의 반환값을 raw에 대입합니다.
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        # HTTPError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except HTTPError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise OllamaHTTPFailure(error.code) from error
        # TimeoutError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except TimeoutError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise OllamaTimeoutFailure from error
        # URLError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except URLError as error:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(error.reason,
            # TimeoutError).
            if isinstance(error.reason, TimeoutError):
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise OllamaTimeoutFailure from error
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise OllamaConnectionFailure from error
        # OSError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except OSError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise OllamaConnectionFailure from error

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(raw) > _MAX_RESPONSE_BYTES.
        if len(raw) > _MAX_RESPONSE_BYTES:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("Ollama 응답이 허용 크기를 초과했습니다.")
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # json.loads()의 반환값을 parsed에 대입합니다.
            parsed = json.loads(raw.decode("utf-8"))
        # (UnicodeError, JSONDecodeError)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
        # 담깁니다.
        except (UnicodeError, JSONDecodeError) as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("Ollama 응답 JSON이 올바르지 않습니다.") from error
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(parsed, dict).
        if not isinstance(parsed, dict):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("Ollama 응답 최상위 값이 객체가 아닙니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return cast(dict[str, Any], parsed)


# OllamaModelInfo: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class OllamaModelInfo:
    # name: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    name: str
    # digest: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    digest: str
    # size_bytes: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    size_bytes: int
    # parameter_size: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    parameter_size: str
    # quantization: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    quantization: str


# OllamaClient: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class OllamaClient:
    """Map Ollama's local chat API to the provider-neutral LLM contract."""

    # name에 문자열을 대입합니다.
    name = "ollama"

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: settings, transport, launcher.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        settings: LLMSettings,
        *,
        transport: OllamaTransport | None = None,
        launcher: OllamaLauncher | None = None,
    ) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: settings.base_url != OLLAMA_BASE_URL.
        if settings.base_url != OLLAMA_BASE_URL:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("Ollama base URL은 고정 loopback 주소여야 합니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not settings.local_only.
        if not settings.local_only:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("Ollama 클라이언트는 local_only=true만 지원합니다.")
        # 오른쪽 식을 계산한 값을 self._settings에 대입합니다.
        self._settings = settings
        # 오른쪽 식을 계산한 값을 self._transport에 대입합니다.
        self._transport = transport or UrllibOllamaTransport()
        # 오른쪽 식을 계산한 값을 self._launcher에 대입합니다.
        self._launcher = launcher

    # verify_model(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: timeout_s.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: OllamaModelInfo.
    def verify_model(self, *, timeout_s: float = 5.0) -> OllamaModelInfo:
        """Verify the installed tag and full manifest digest before chat starts."""
        # validate_request_limits()으로 입력 형식과 허용 조건을 검사합니다.
        validate_request_limits(
            timeout_s=timeout_s,
            temperature=None,
            max_output_tokens=None,
        )
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # self._transport.request_json()의 반환값을 response에 대입합니다.
            response = self._transport.request_json(
                "GET",
                f"{OLLAMA_BASE_URL}/api/tags",
                None,
                timeout_s=timeout_s,
            )
        # OllamaTimeoutFailure를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except OllamaTimeoutFailure as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMTimeout("Ollama 모델 확인 시간이 초과되었습니다.") from error
        # OllamaConnectionFailure를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except OllamaConnectionFailure as error:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._launcher and
            # self._launcher.ensure_running().
            if self._launcher and self._launcher.ensure_running():
                # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를
                # 처리합니다.
                try:
                    # self._transport.request_json()의 반환값을 response에 대입합니다.
                    response = self._transport.request_json(
                        "GET",
                        f"{OLLAMA_BASE_URL}/api/tags",
                        None,
                        timeout_s=timeout_s,
                    )
                # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
                except Exception as retry_err:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise LLMUnavailable(
                        "Ollama에 연결할 수 없습니다. Ollama가 실행 중인지 확인하세요."
                    ) from retry_err
            # 앞선 조건이 거짓이면 이 블록을 실행합니다.
            else:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise LLMUnavailable(
                    "Ollama에 연결할 수 없습니다. Ollama가 실행 중인지 확인하세요."
                ) from error
        # OllamaHTTPFailure를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except OllamaHTTPFailure as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMUnavailable(
                "Ollama 모델 목록을 확인할 수 없습니다.",
                {"status": error.status},
            ) from error

        # response.get()의 반환값을 models에 대입합니다.
        models = response.get("models")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(models, list).
        if not isinstance(models, list):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("Ollama 모델 목록 형식이 올바르지 않습니다.")
        # next()의 반환값을 selected에 대입합니다.
        selected = next(
            (
                item
                for item in models
                if isinstance(item, dict) and item.get("name") == self._settings.model
            ),
            None,
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: selected is None.
        if selected is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMUnavailable(
                f"로컬 모델 {self._settings.model}이 없습니다. ollama pull을 실행하세요."
            )
        # selected.get()의 반환값을 digest에 대입합니다.
        digest = selected.get("digest")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: digest != self._settings.model_digest.
        if digest != self._settings.model_digest:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("설치된 Ollama 모델 digest가 D005 결정과 다릅니다.")
        # selected.get()의 반환값을 details에 대입합니다.
        details = selected.get("details")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(details, dict).
        if not isinstance(details, dict):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("Ollama 모델 상세 정보 형식이 올바르지 않습니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return OllamaModelInfo(
            name=self._settings.model,
            digest=digest,
            size_bytes=_nonnegative_int(selected.get("size"), "model.size"),
            parameter_size=_required_string(details.get("parameter_size"), "parameter_size"),
            quantization=_required_string(details.get("quantization_level"), "quantization"),
        )

    # complete(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: messages, tools, timeout_s, ctx, temperature, max_output_tokens.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: LLMResponse.
    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        timeout_s: float,
        ctx: RequestContext,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        # validate_request_limits()으로 입력 형식과 허용 조건을 검사합니다.
        validate_request_limits(
            timeout_s=timeout_s,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not messages.
        if not messages:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("Ollama 요청에는 메시지가 하나 이상 필요합니다.")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not self._settings.native_tool_calling_enabled and (
            tools or any(message.role == "tool" or message.tool_calls for message in messages)
        ):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("네이티브 도구 호출 기능이 비활성화되어 있습니다.")
        # 오른쪽 식을 계산한 값을 output_limit에 대입합니다.
        output_limit = max_output_tokens or self._settings.max_output_tokens
        # 오른쪽 식을 계산한 값을 selected_temperature에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        selected_temperature = self._settings.temperature if temperature is None else temperature
        # self.count_tokens()의 반환값을 prompt_tokens_est에 대입합니다.
        prompt_tokens_est = self.count_tokens(messages)
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if prompt_tokens_est + output_limit > self._settings.runtime_context_tokens:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("Ollama 요청이 설정된 16K 문맥 한도를 초과합니다.")
        # _serialize_tools()의 반환값을 ollama_tools에 대입합니다.
        ollama_tools = _serialize_tools(tools)
        # payload에 딕셔너리(키와 값의 쌍)을 대입합니다.
        payload: dict[str, Any] = {
            "model": self._settings.model,
            "messages": [_serialize_message(message) for message in messages],
            "stream": False,
            "think": self._settings.think,
            "options": {
                "temperature": selected_temperature,
                "num_predict": output_limit,
                "num_ctx": self._settings.runtime_context_tokens,
            },
        }
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ollama_tools.
        if response_schema is not None:
            payload["format"] = response_schema
        if ollama_tools:
            # 오른쪽 식을 계산한 값을 payload['tools']에 대입합니다.
            payload["tools"] = ollama_tools
        # _prompt_version()의 반환값을 prompt_version에 대입합니다.
        prompt_version = _prompt_version(messages)

        # for 반복문: 대상의 항목을 하나씩 attempt에 대입하며 아래 블록을 실행합니다.
        for attempt in range(1, self._settings.max_retries + 2):
            # ctx.cancel.raise_if_cancelled()을 호출해 작업을 수행합니다.
            ctx.cancel.raise_if_cancelled()
            # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
            ctx.events.emit(
                "llm.request",
                {
                    "model": self._settings.model,
                    "attempt": attempt,
                    "prompt_tokens_est": prompt_tokens_est,
                    "prompt_version": prompt_version,
                    "tool_count": len(ollama_tools),
                    "memory_record_ids": list(getattr(ctx, "memory_record_ids", ())),
                },
            )
            # ctx.clock.monotonic_ms()의 반환값을 started_ms에 대입합니다.
            started_ms = ctx.clock.monotonic_ms()
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # self._transport.request_json()의 반환값을 raw_response에 대입합니다.
                raw_response = self._transport.request_json(
                    "POST",
                    f"{OLLAMA_BASE_URL}/api/chat",
                    payload,
                    timeout_s=timeout_s,
                )
            # OllamaTimeoutFailure를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
            # 담깁니다.
            except OllamaTimeoutFailure as error:
                # self._retry_or_raise()을 호출해 작업을 수행합니다.
                self._retry_or_raise("timeout", attempt, ctx, error)
                # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                continue
            # OllamaConnectionFailure를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
            # 담깁니다.
            except OllamaConnectionFailure as error:
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._launcher and
                # self._launcher.ensure_running().
                if self._launcher and self._launcher.ensure_running():
                    # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                    continue
                # self._retry_or_raise()을 호출해 작업을 수행합니다.
                self._retry_or_raise("connection_error", attempt, ctx, error)
                # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                continue
            # OllamaHTTPFailure를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
            except OllamaHTTPFailure as error:
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 500 <= error.status <= 599.
                if 500 <= error.status <= 599:
                    # self._retry_or_raise()을 호출해 작업을 수행합니다.
                    self._retry_or_raise("server_error", attempt, ctx, error)
                    # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                    continue
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise LLMBadResponse(
                    "Ollama가 요청을 거부했습니다.",
                    {"status": error.status},
                ) from error

            # self._parse_response()의 반환값을 response에 대입합니다.
            response = self._parse_response(
                raw_response,
                tools=tools,
                started_ms=started_ms,
                ctx=ctx,
            )
            # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
            ctx.events.emit(
                "llm.response",
                {
                    "model": response.model,
                    "finish_reason": response.finish_reason,
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "cost_usd": format(response.usage.cost_usd, "f"),
                    "latency_ms": response.usage.latency_ms,
                    "tool_call_names": [call.name for call in response.tool_calls],
                },
            )
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return response

        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise AssertionError("Ollama retry loop terminated unexpectedly")

    # count_tokens(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: messages.
    # 반환 타입 힌트: 정수(int).
    def count_tokens(self, messages: Sequence[Message]) -> int:
        """Budget UTF-8 bytes plus template allowance, not an exact token count.

        Qwen's byte-fallback tokenizer cannot require more text tokens than UTF-8
        bytes. Reserve per-message and outer chat-template overhead as well.
        Actual usage is still read from Ollama's prompt_eval_count response.
        """
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return 64 + sum(32 + max(1, len(message.content.encode("utf-8"))) for message in messages)

    # _retry_or_raise(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: reason, attempt, ctx, error.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _retry_or_raise(
        self,
        reason: str,
        attempt: int,
        ctx: RequestContext,
        error: Exception,
    ) -> None:
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if reason not in self._settings.retry_on or attempt > self._settings.max_retries:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: reason == 'timeout'.
            if reason == "timeout":
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise LLMTimeout(
                    "Ollama 응답 시간이 초과되었습니다.",
                    {"attempts": attempt},
                ) from error
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMUnavailable(
                "Ollama가 응답하지 않습니다. 실행 상태와 모델을 확인하세요.",
                {"reason": reason, "attempts": attempt},
            ) from error

        # min()의 반환값을 base_wait에 대입합니다.
        base_wait = min(
            self._settings.backoff_max_s,
            self._settings.backoff_base_s * (2 ** (attempt - 1)),
        )
        # min()의 반환값을 wait_s에 대입합니다.
        wait_s = min(
            self._settings.backoff_max_s,
            base_wait + ctx.random.uniform(0.0, base_wait * 0.25),
        )
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        ctx.events.emit(
            "llm.retry",
            {"attempt": attempt, "reason": reason, "wait_ms": round(wait_s * 1000)},
        )
        # ctx.cancel.raise_if_cancelled()을 호출해 작업을 수행합니다.
        ctx.cancel.raise_if_cancelled()
        # 지정한 시간만큼 현재 실행을 기다리게 합니다.
        ctx.sleeper.sleep(wait_s)

    # _parse_response(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: response, tools, started_ms, ctx.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: LLMResponse.
    def _parse_response(
        self,
        response: Mapping[str, Any],
        *,
        tools: Sequence[ToolSpec],
        started_ms: int,
        ctx: RequestContext,
    ) -> LLMResponse:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: response.get('done') is not True.
        if response.get("done") is not True:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("Ollama가 완료되지 않은 응답을 반환했습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: response.get('model') !=
        # self._settings.model.
        if response.get("model") != self._settings.model:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("Ollama 응답 모델이 설정과 일치하지 않습니다.")
        # response.get()의 반환값을 message에 대입합니다.
        message = response.get("message")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not isinstance(message, dict) or message.get("role") != "assistant":
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("Ollama assistant 메시지 형식이 올바르지 않습니다.")
        # _parse_tool_calls()의 반환값을 tool_calls에 대입합니다.
        tool_calls = _parse_tool_calls(
            message.get("tool_calls"),
            tools=tools,
            request_id=ctx.request_id,
        )
        # message.get()의 반환값을 content에 대입합니다.
        content = message.get("content")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: content is None and tool_calls.
        if content is None and tool_calls:
            # text을 아직 값이 없음을 뜻하는 None으로 설정합니다.
            text = None
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(content, str).
        elif isinstance(content, str):
            # 오른쪽 식을 계산한 값을 text에 대입합니다.
            text = content
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("Ollama 응답의 message.content 값이 올바르지 않습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not tool_calls and (not text).
        if not tool_calls and not text:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("Ollama 응답의 message.content 값이 올바르지 않습니다.")
        # response.get()의 반환값을 done_reason에 대입합니다.
        done_reason = response.get("done_reason")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: done_reason not in {'stop', 'length'}.
        if done_reason not in {"stop", "length"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("알 수 없는 Ollama 종료 사유입니다.")

        # _nonnegative_int()의 반환값을 prompt_tokens에 대입합니다.
        prompt_tokens = _nonnegative_int(response.get("prompt_eval_count"), "prompt_eval_count")
        # _nonnegative_int()의 반환값을 completion_tokens에 대입합니다.
        completion_tokens = _nonnegative_int(response.get("eval_count"), "eval_count")
        # response.get()의 반환값을 total_duration에 대입합니다.
        total_duration = response.get("total_duration")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: total_duration is None.
        if total_duration is None:
            # max()의 반환값을 latency_ms에 대입합니다.
            latency_ms = max(0, ctx.clock.monotonic_ms() - started_ms)
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # 오른쪽 식을 계산한 값을 latency_ms에 대입합니다.
            latency_ms = _nonnegative_int(total_duration, "total_duration") // 1_000_000
        # 오른쪽 식을 계산한 값을 pricing에 대입합니다.
        pricing = self._settings.pricing[self._settings.model]
        # 오른쪽 식을 계산한 값을 cost에 대입합니다.
        cost = (
            Decimal(prompt_tokens) * pricing.input_per_1k
            + Decimal(completion_tokens) * pricing.output_per_1k
        ) / Decimal(1000)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            usage=LLMUsage(prompt_tokens, completion_tokens, cost, latency_ms),
            model=self._settings.model,
            finish_reason="tool_calls" if tool_calls else done_reason,
        )


# _serialize_tools(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tools.
# 반환 타입 힌트: list[dict[str, Any]].
def _serialize_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    """Convert trusted registry specs without exposing policy metadata to the model."""
    # serialized에 리스트(순서가 있고 수정 가능)을 대입합니다.
    serialized: list[dict[str, Any]] = []
    # set()의 반환값을 seen에 대입합니다.
    seen: set[str] = set()
    # for 반복문: 대상의 항목을 하나씩 spec에 대입하며 아래 블록을 실행합니다.
    for spec in tools:
        # _tool_spec_name()의 반환값을 name에 대입합니다.
        name = _tool_spec_name(spec)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: name in seen.
        if name in seen:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError(f"Ollama 도구 이름이 중복되었습니다: {name}")
        # add 메서드를 호출해 항목이나 기록을 추가합니다.
        seen.add(name)
        # getattr()의 반환값을 description에 대입합니다.
        description = getattr(spec, "description", None)
        # getattr()의 반환값을 schema에 대입합니다.
        schema = getattr(spec, "json_schema", None)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(description, str) or
        # not
        # description.strip().
        if not isinstance(description, str) or not description.strip():
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError(f"Ollama 도구 {name} 설명이 올바르지 않습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(schema, dict).
        if not isinstance(schema, dict):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError(f"Ollama 도구 {name} JSON Schema가 올바르지 않습니다.")
        # 리스트 끝에 항목 하나를 추가합니다.
        serialized.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": schema,
                },
            }
        )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return serialized


# _serialize_message(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: message.
# 반환 타입 힌트: dict[str, Any].
def _serialize_message(message: Message) -> dict[str, Any]:
    """Map provider-neutral message history to the documented Ollama shape."""
    # payload에 딕셔너리(키와 값의 쌍)을 대입합니다.
    payload: dict[str, Any] = {"role": message.role, "content": message.content}
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: message.role == 'assistant' and
    # message.tool_calls.
    if message.role == "assistant" and message.tool_calls:
        # 오른쪽 식을 계산한 값을 payload['tool_calls']에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        payload["tool_calls"] = [
            {
                "function": {
                    "name": call.name,
                    "arguments": call.arguments,
                },
            }
            for call in message.tool_calls
        ]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: message.role == 'tool'.
    if message.role == "tool":
        # Ollama associates a result with tool_name, not an OpenAI-style call ID.
        # 오른쪽 식을 계산한 값을 payload['tool_name']에 대입합니다.
        payload["tool_name"] = message.name
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return payload


# _parse_tool_calls(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value, tools, request_id.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: tuple[ToolCall, ...].
def _parse_tool_calls(
    value: Any,
    *,
    tools: Sequence[ToolSpec],
    request_id: str,
) -> tuple[ToolCall, ...]:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: value is None.
    if value is None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(value, list).
    if not isinstance(value, list):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse("Ollama 도구 호출 목록 형식이 올바르지 않습니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not value.
    if not value:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(value) != 1.
    if len(value) != 1:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse("한 응답에는 도구 호출 하나만 허용됩니다.")

    # 오른쪽 식을 계산한 값을 known_names에 대입합니다.
    # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
    known_names = {_tool_spec_name(spec) for spec in tools}
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not known_names.
    if not known_names:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse("활성 도구 없이 Ollama 도구 호출을 받을 수 없습니다.")
    # 오른쪽 식을 계산한 값을 item에 대입합니다.
    item = value[0]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(item, dict).
    if not isinstance(item, dict):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse("Ollama 도구 호출 항목 형식이 올바르지 않습니다.")
    # item.get()의 반환값을 function에 대입합니다.
    function = item.get("function")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(function, dict).
    if not isinstance(function, dict):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse("Ollama 도구 함수 형식이 올바르지 않습니다.")
    # _tool_name()의 반환값을 name에 대입합니다.
    name = _tool_name(function.get("name"), field="function.name")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: name not in known_names.
    if name not in known_names:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse("Ollama가 등록되지 않은 도구를 요청했습니다.")
    # function.get()의 반환값을 arguments에 대입합니다.
    arguments = function.get("arguments")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(arguments, dict).
    if not isinstance(arguments, dict):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse("Ollama 도구 인자는 객체여야 합니다.")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return (
        ToolCall(
            id=f"{request_id}:tool:0",
            name=name,
            arguments=cast(dict[str, Any], arguments),
        ),
    )


# _tool_spec_name(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: spec.
# 반환 타입 힌트: 문자열(str).
def _tool_spec_name(spec: ToolSpec) -> str:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return _tool_name(getattr(spec, "name", None), field="tool.name")


# _tool_name(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value, field.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 문자열(str).
def _tool_name(value: Any, *, field: str) -> str:
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if not isinstance(value, str) or not value or len(value) > _MAX_TOOL_NAME_LENGTH:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse(f"Ollama {field} 값이 올바르지 않습니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _CONTROL_CHARS.search(value).
    if _CONTROL_CHARS.search(value):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse(f"Ollama {field}에 제어 문자가 포함되어 있습니다.")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return value


# _prompt_version(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: messages.
# 반환 타입 힌트: 문자열(str).
def _prompt_version(messages: Sequence[Message]) -> str:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: messages and messages[0].role == 'system'.
    if messages and messages[0].role == "system":
        # messages[0].content.splitlines()의 반환값을 lines에 대입합니다.
        lines = messages[0].content.splitlines()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: lines.
        if lines:
            # _PROMPT_VERSION.match()의 반환값을 match에 대입합니다.
            match = _PROMPT_VERSION.match(lines[0])
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match is not None.
            if match is not None:
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return match.group(1)
    # 'unversioned'을 반환하고 이 함수의 실행을 끝냅니다.
    return "unversioned"


# _required_string(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value, field.
# 반환 타입 힌트: 문자열(str).
def _required_string(value: Any, field: str) -> str:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(value, str) or not value.
    if not isinstance(value, str) or not value:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse(f"Ollama 응답의 {field} 값이 올바르지 않습니다.")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return value


# _nonnegative_int(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value, field.
# 반환 타입 힌트: 정수(int).
def _nonnegative_int(value: Any, field: str) -> int:
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse(f"Ollama 응답의 {field} 값이 올바르지 않습니다.")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return value

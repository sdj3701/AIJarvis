# 파이썬 공부 | scripts/tests/unit/test_ollama_client.py
# ollama_client 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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
from app.llm.base import Message, ToolCall
from app.llm.ollama_client import (
    OllamaClient,
    OllamaConnectionFailure,
    OllamaHTTPFailure,
    OllamaTimeoutFailure,
    UrllibOllamaTransport,
)
from app.tools.base import ToolSpec
from tests.fakes.clock import FixedRandom, FrozenClock, ImmediateSleeper

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase1
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


# ScriptedTransport: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class ScriptedTransport:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # *script는 추가 위치 인자를 튜플로 모읍니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, *script: Mapping[str, Any] | Exception) -> None:
        # list()의 반환값을 self.script에 대입합니다.
        self.script = list(script)
        # self.requests에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.requests: list[tuple[str, str, Mapping[str, Any] | None, float]] = []

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
        # 리스트 끝에 항목 하나를 추가합니다.
        self.requests.append((method, url, payload, timeout_s))
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self.script.
        if not self.script:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise AssertionError("unexpected Ollama transport call")
        # self.script.pop()의 반환값을 result에 대입합니다.
        result = self.script.pop(0)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(result, Exception).
        if isinstance(result, Exception):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise result
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return result


# RecordingEvents: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class RecordingEvents:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # self.records에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.records: list[tuple[str, Mapping[str, Any]]] = []

    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.records.append((event_type, payload))


# ActiveCancellation: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class ActiveCancellation:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: cancelled.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, *, cancelled: bool = False) -> None:
        # 오른쪽 식을 계산한 값을 self.cancelled에 대입합니다.
        self.cancelled = cancelled

    # raise_if_cancelled(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def raise_if_cancelled(self) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.cancelled.
        if self.cancelled:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise InterruptedError("cancelled")


# FakeHTTPResponse: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeHTTPResponse:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: body.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, body: bytes) -> None:
        # 오른쪽 식을 계산한 값을 self.body에 대입합니다.
        self.body = body

    # __enter__(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: FakeHTTPResponse.
    def __enter__(self) -> FakeHTTPResponse:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self

    # __exit__(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # *args는 추가 위치 인자를 튜플로 모읍니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __exit__(self, *args: object) -> None:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del args

    # read(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: limit.
    # 반환 타입 힌트: 바이트 데이터(bytes).
    def read(self, limit: int) -> bytes:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del limit
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.body


# _llm_settings(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: LLMSettings.
def _llm_settings() -> LLMSettings:
    # yaml.safe_load()의 반환값을 document에 대입합니다.
    document = yaml.safe_load(
        (REPOSITORY_ROOT / "config" / "settings.example.yaml").read_text(encoding="utf-8")
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return Settings.model_validate(document).llm


# _native_llm_settings(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: LLMSettings.
def _native_llm_settings() -> LLMSettings:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return _llm_settings().model_copy(update={"native_tool_calling_enabled": True})


# _context(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: events, sleeper, cancelled.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: RequestContext.
def _context(
    *,
    events: RecordingEvents | None = None,
    sleeper: ImmediateSleeper | None = None,
    cancelled: bool = False,
) -> RequestContext:
    # datetime()의 반환값을 current에 대입합니다.
    current = datetime(2026, 8, 11, 12, 0, tzinfo=KST)
    # 아래 함수()의 반환값을 value에 대입합니다.
    value = type(
        "OllamaTestContext",
        (),
        {
            "cancel": ActiveCancellation(cancelled=cancelled),
            "events": events or RecordingEvents(),
            "clock": FrozenClock(current),
            "random": FixedRandom(0.0),
            "sleeper": sleeper or ImmediateSleeper(),
            "request_id": "req_01J00000000000000000000000",
        },
    )()
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return cast(RequestContext, value)


# _chat_response(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# **updates는 추가 이름 인자를 딕셔너리로 모읍니다.
# 반환 타입 힌트: dict[str, Any].
def _chat_response(**updates: Any) -> dict[str, Any]:
    # response에 딕셔너리(키와 값의 쌍)을 대입합니다.
    response: dict[str, Any] = {
        "model": "qwen3.5:9b",
        "message": {"role": "assistant", "content": "네, 준비되었습니다."},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 12,
        "eval_count": 7,
        "total_duration": 42_000_000,
    }
    # response.update()을 호출해 작업을 수행합니다.
    response.update(updates)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return response


def test_json_schema_is_sent_only_when_requested() -> None:
    transport = ScriptedTransport(_chat_response(), _chat_response())
    client = OllamaClient(_llm_settings(), transport=transport)
    schema = {"type": "object", "properties": {"status": {"type": "string"}}}
    client.complete(
        messages=[Message("user", "JSON")], timeout_s=10, ctx=_context(), response_schema=schema
    )
    client.complete(messages=[Message("user", "일반 대화")], timeout_s=10, ctx=_context())
    assert transport.requests[0][2]["format"] == schema
    assert "format" not in transport.requests[1][2]


# _tool_spec(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: name.
# 반환 타입 힌트: ToolSpec.
def _tool_spec(name: str = "web_search") -> ToolSpec:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return ToolSpec(
        name=name,
        description="검색 도구",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {"query": {"type": "string", "maxLength": 300}},
        },
        risk="low",
        capabilities=frozenset({"net_http"}),
        execution_mode="in_process",
        idempotent=True,
        enabled=True,
        untrusted_output=True,
        timeout_s=10,
        phase=3,
    )


# _tags_response(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: digest.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: dict[str, Any].
def _tags_response(*, digest: str | None = None) -> dict[str, Any]:
    # 오른쪽 식을 계산한 값을 selected_digest에 대입합니다.
    selected_digest = digest or _llm_settings().model_digest
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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


# pytest가 test_urllib_transport_sends_utf8_json_and_parses_object()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_urllib_transport_sends_utf8_json_and_parses_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # captured에 리스트(순서가 있고 수정 가능)을 대입합니다.
    captured: list[tuple[Any, float]] = []

    # fake_urlopen(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: request, timeout.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: FakeHTTPResponse.
    def fake_urlopen(request: Any, *, timeout: float) -> FakeHTTPResponse:
        # 리스트 끝에 항목 하나를 추가합니다.
        captured.append((request, timeout))
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return FakeHTTPResponse('{"answer":"안녕"}'.encode())

    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr("app.llm.ollama_client.urlopen", fake_urlopen)
    # UrllibOllamaTransport().request_json()의 반환값을 response에 대입합니다.
    response = UrllibOllamaTransport().request_json(
        "POST",
        "http://127.0.0.1:11434/api/chat",
        {"text": "한글"},
        timeout_s=2.5,
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response == {"answer": "안녕"}
    # 언패킹: 오른쪽 결과를 순서대로 (request, timeout)에 나누어 담습니다.
    request, timeout = captured[0]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert timeout == 2.5
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert request.full_url == "http://127.0.0.1:11434/api/chat"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert request.method == "POST"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert request.data.decode() == '{"text":"한글"}'
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert request.get_header("Content-type") == "application/json; charset=utf-8"


# pytest가 test_urllib_transport_maps_network_failures()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: monkeypatch, failure, expected.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
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
    # fail(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # *args는 추가 위치 인자를 튜플로 모읍니다.
    # **kwargs는 추가 이름 인자를 딕셔너리로 모읍니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def fail(*args: object, **kwargs: object) -> None:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del args, kwargs
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise failure

    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr("app.llm.ollama_client.urlopen", fail)
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(expected):
        # UrllibOllamaTransport().request_json()을 호출해 작업을 수행합니다.
        UrllibOllamaTransport().request_json(
            "GET",
            "http://127.0.0.1:11434/api/tags",
            None,
            timeout_s=1,
        )


# pytest가 test_urllib_transport_rejects_invalid_json_shapes()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: monkeypatch, body.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("body", [b"not-json", b"[]"])
def test_urllib_transport_rejects_invalid_json_shapes(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr(
        "app.llm.ollama_client.urlopen",
        lambda *args, **kwargs: FakeHTTPResponse(body),
    )
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(LLMBadResponse):
        # UrllibOllamaTransport().request_json()을 호출해 작업을 수행합니다.
        UrllibOllamaTransport().request_json(
            "GET",
            "http://127.0.0.1:11434/api/tags",
            None,
            timeout_s=1,
        )


# pytest가 test_urllib_transport_rejects_oversized_response()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_urllib_transport_rejects_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr("app.llm.ollama_client._MAX_RESPONSE_BYTES", 4)
    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr(
        "app.llm.ollama_client.urlopen",
        lambda *args, **kwargs: FakeHTTPResponse(b"12345"),
    )
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(LLMBadResponse, match="크기"):
        # UrllibOllamaTransport().request_json()을 호출해 작업을 수행합니다.
        UrllibOllamaTransport().request_json(
            "GET",
            "http://127.0.0.1:11434/api/tags",
            None,
            timeout_s=1,
        )


# pytest가 test_verify_model_checks_exact_tag_and_digest()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_verify_model_checks_exact_tag_and_digest() -> None:
    # ScriptedTransport()의 반환값을 transport에 대입합니다.
    transport = ScriptedTransport(_tags_response())
    # 아래 함수()의 반환값을 info에 대입합니다.
    info = OllamaClient(_llm_settings(), transport=transport).verify_model(timeout_s=3)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert info.name == "qwen3.5:9b"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert info.quantization == "Q4_K_M"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert info.size_bytes == 6_594_474_711
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert transport.requests == [("GET", "http://127.0.0.1:11434/api/tags", None, 3)]


# pytest가 test_verify_model_maps_transport_failures()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: failure, expected.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
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
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(expected):
        # 아래 함수()을 호출해 작업을 수행합니다.
        OllamaClient(_llm_settings(), transport=ScriptedTransport(failure)).verify_model()


# pytest가 test_verify_model_rejects_missing_changed_or_malformed_model()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: response.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
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
    # OllamaClient()의 반환값을 client에 대입합니다.
    client = OllamaClient(_llm_settings(), transport=ScriptedTransport(response))

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises((LLMUnavailable, LLMBadResponse)):
        # client.verify_model()을 호출해 작업을 수행합니다.
        client.verify_model()


# pytest가 test_complete_maps_request_response_usage_and_events()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_complete_maps_request_response_usage_and_events() -> None:
    # ScriptedTransport()의 반환값을 transport에 대입합니다.
    transport = ScriptedTransport(_chat_response())
    # RecordingEvents()의 반환값을 events에 대입합니다.
    events = RecordingEvents()
    # OllamaClient()의 반환값을 client에 대입합니다.
    client = OllamaClient(_llm_settings(), transport=transport)
    # messages에 리스트(순서가 있고 수정 가능)을 대입합니다.
    messages = [
        Message("system", "<!-- version: 1 -->\n한국어로 답하세요."),
        Message("user", "준비됐나요?"),
    ]

    # client.complete()의 반환값을 response에 대입합니다.
    response = client.complete(messages=messages, timeout_s=30, ctx=_context(events=events))

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response.text == "네, 준비되었습니다."
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response.usage.prompt_tokens == 12
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response.usage.completion_tokens == 7
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response.usage.cost_usd == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response.usage.latency_ms == 42
    # 언패킹: 오른쪽 결과를 순서대로 (method, url, payload, timeout_s)에 나누어 담습니다.
    method, url, payload, timeout_s = transport.requests[0]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert (method, url, timeout_s) == ("POST", "http://127.0.0.1:11434/api/chat", 30)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert payload is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert payload["model"] == "qwen3.5:9b"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert payload["stream"] is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert payload["think"] is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert payload["options"] == {
        "temperature": 0.3,
        "num_predict": 2000,
        "num_ctx": 16384,
    }
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [event_type for event_type, _ in events.records] == ["llm.request", "llm.response"]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.records[0][1]["prompt_version"] == "1"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.records[1][1]["cost_usd"] == "0.00"


# pytest가 test_retryable_failures_back_off_then_succeed()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: failure, reason.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (OllamaTimeoutFailure(), "timeout"),
        (OllamaConnectionFailure(), "connection_error"),
        (OllamaHTTPFailure(503), "server_error"),
    ],
)
def test_retryable_failures_back_off_then_succeed(failure: Exception, reason: str) -> None:
    # ScriptedTransport()의 반환값을 transport에 대입합니다.
    transport = ScriptedTransport(failure, _chat_response())
    # ImmediateSleeper()의 반환값을 sleeper에 대입합니다.
    sleeper = ImmediateSleeper()
    # RecordingEvents()의 반환값을 events에 대입합니다.
    events = RecordingEvents()
    # 아래 함수()의 반환값을 response에 대입합니다.
    response = OllamaClient(_llm_settings(), transport=transport).complete(
        messages=[Message("user", "재시도")],
        timeout_s=5,
        ctx=_context(events=events, sleeper=sleeper),
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response.text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert sleeper.durations == [0.5]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(transport.requests) == 2
    # next()의 반환값을 retry에 대입합니다.
    retry = next(payload for event, payload in events.records if event == "llm.retry")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert retry == {"attempt": 1, "reason": reason, "wait_ms": 500}


# pytest가 test_retry_gives_up_after_configured_max_without_real_sleep()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_retry_gives_up_after_configured_max_without_real_sleep() -> None:
    # ScriptedTransport()의 반환값을 transport에 대입합니다.
    transport = ScriptedTransport(*(OllamaTimeoutFailure() for _ in range(4)))
    # ImmediateSleeper()의 반환값을 sleeper에 대입합니다.
    sleeper = ImmediateSleeper()

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(LLMTimeout) as captured:
        # OllamaClient(_llm_settings(), transport=transport).complete()을 호출해 작업을
        # 수행합니다.
        OllamaClient(_llm_settings(), transport=transport).complete(
            messages=[Message("user", "시간 초과")],
            timeout_s=1,
            ctx=_context(sleeper=sleeper),
        )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured.value.detail["attempts"] == 4
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert sleeper.durations == [0.5, 1.0, 2.0]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(transport.requests) == 4


# pytest가 test_connection_failure_gives_up_as_unavailable()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_connection_failure_gives_up_as_unavailable() -> None:
    # ScriptedTransport()의 반환값을 transport에 대입합니다.
    transport = ScriptedTransport(*(OllamaConnectionFailure() for _ in range(4)))

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(LLMUnavailable) as captured:
        # OllamaClient(_llm_settings(), transport=transport).complete()을 호출해 작업을
        # 수행합니다.
        OllamaClient(_llm_settings(), transport=transport).complete(
            messages=[Message("user", "연결 실패")],
            timeout_s=1,
            ctx=_context(),
        )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured.value.detail == {"reason": "connection_error", "attempts": 4}


# pytest가 test_http_4xx_is_not_retried()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_http_4xx_is_not_retried() -> None:
    # ScriptedTransport()의 반환값을 transport에 대입합니다.
    transport = ScriptedTransport(OllamaHTTPFailure(404), _chat_response())

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(LLMBadResponse) as captured:
        # OllamaClient(_llm_settings(), transport=transport).complete()을 호출해 작업을
        # 수행합니다.
        OllamaClient(_llm_settings(), transport=transport).complete(
            messages=[Message("user", "없는 모델")],
            timeout_s=1,
            ctx=_context(),
        )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured.value.detail == {"status": 404}
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(transport.requests) == 1


# pytest가 test_malformed_or_unsupported_responses_are_rejected()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: response.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
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
    # OllamaClient()의 반환값을 client에 대입합니다.
    client = OllamaClient(_llm_settings(), transport=ScriptedTransport(response))

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(LLMBadResponse):
        # client.complete()을 호출해 작업을 수행합니다.
        client.complete(
            messages=[Message("user", "검증")],
            timeout_s=1,
            ctx=_context(),
        )


# pytest가 test_native_tools_and_tool_messages_are_serialized_without_internal_call_ids()을 실행해
# 아래
# 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_native_tools_and_tool_messages_are_serialized_without_internal_call_ids() -> None:
    # ScriptedTransport()의 반환값을 transport에 대입합니다.
    transport = ScriptedTransport(_chat_response())
    # OllamaClient()의 반환값을 client에 대입합니다.
    client = OllamaClient(_native_llm_settings(), transport=transport)
    # ToolCall()의 반환값을 call에 대입합니다.
    call = ToolCall("internal-call", "web_search", {"query": "Jarvis"})

    # client.complete()의 반환값을 response에 대입합니다.
    response = client.complete(
        messages=[
            Message("user", "검색해줘"),
            Message("assistant", "", tool_calls=(call,)),
            Message("tool", "검색 결과", tool_call_id=call.id, name=call.name),
        ],
        tools=[_tool_spec()],
        timeout_s=1,
        ctx=_context(),
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response.text == "네, 준비되었습니다."
    # 오른쪽 식을 계산한 값을 payload에 대입합니다.
    payload = transport.requests[0][2]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert payload is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert payload["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "검색 도구",
                "parameters": _tool_spec().json_schema,
            },
        }
    ]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert payload["messages"][1]["tool_calls"] == [
        {"function": {"name": "web_search", "arguments": {"query": "Jarvis"}}}
    ]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert payload["messages"][2] == {
        "role": "tool",
        "content": "검색 결과",
        "tool_name": "web_search",
    }


# pytest가 test_disabled_native_tool_calling_does_not_reach_transport()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_disabled_native_tool_calling_does_not_reach_transport() -> None:
    # ScriptedTransport()의 반환값을 transport에 대입합니다.
    transport = ScriptedTransport(_chat_response())

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(LLMBadResponse, match="비활성화"):
        # OllamaClient(_llm_settings(), transport=transport).complete()을 호출해 작업을
        # 수행합니다.
        OllamaClient(_llm_settings(), transport=transport).complete(
            messages=[Message("user", "검색해줘")],
            tools=[_tool_spec()],
            timeout_s=1,
            ctx=_context(),
        )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert transport.requests == []


# pytest가 test_native_tool_response_is_normalized_and_bound_to_registered_tool()을 실행해 아래
# 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_native_tool_response_is_normalized_and_bound_to_registered_tool() -> None:
    # ScriptedTransport()의 반환값을 transport에 대입합니다.
    transport = ScriptedTransport(
        _chat_response(
            message={
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "web_search", "arguments": {"query": "Jarvis"}}}
                ],
            }
        )
    )

    # 아래 함수()의 반환값을 response에 대입합니다.
    response = OllamaClient(_native_llm_settings(), transport=transport).complete(
        messages=[Message("user", "검색해줘")],
        tools=[_tool_spec()],
        timeout_s=1,
        ctx=_context(),
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response.text == ""
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response.finish_reason == "tool_calls"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response.tool_calls == (
        ToolCall(
            id="req_01J00000000000000000000000:tool:0",
            name="web_search",
            arguments={"query": "Jarvis"},
        ),
    )


# pytest가 test_native_tool_response_rejects_multi_unknown_or_malformed_calls()을 실행해 아래
# 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tool_calls.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize(
    "tool_calls",
    [
        [
            {"function": {"name": "web_search", "arguments": {"query": "Jarvis"}}},
            {"function": {"name": "web_search", "arguments": {"query": "AI"}}},
        ],
        [{"function": {"name": "unknown", "arguments": {"query": "Jarvis"}}}],
        [{"function": {"name": "web_search", "arguments": []}}],
    ],
)
def test_native_tool_response_rejects_multi_unknown_or_malformed_calls(
    tool_calls: list[dict[str, object]],
) -> None:
    # ScriptedTransport()의 반환값을 transport에 대입합니다.
    transport = ScriptedTransport(
        _chat_response(message={"role": "assistant", "content": "", "tool_calls": tool_calls})
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(LLMBadResponse):
        # 아래 함수()을 호출해 작업을 수행합니다.
        OllamaClient(_native_llm_settings(), transport=transport).complete(
            messages=[Message("user", "검색해줘")],
            tools=[_tool_spec()],
            timeout_s=1,
            ctx=_context(),
        )


# pytest가 test_cancelled_native_request_does_not_reach_transport()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_cancelled_native_request_does_not_reach_transport() -> None:
    # ScriptedTransport()의 반환값을 transport에 대입합니다.
    transport = ScriptedTransport(_chat_response())
    # OllamaClient()의 반환값을 client에 대입합니다.
    client = OllamaClient(_native_llm_settings(), transport=transport)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(InterruptedError):
        # client.complete()을 호출해 작업을 수행합니다.
        client.complete(
            messages=[Message("user", "취소")],
            tools=[_tool_spec()],
            timeout_s=1,
            ctx=_context(cancelled=True),
        )
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert transport.requests == []


# pytest가 test_token_estimate_is_deterministic_and_context_limit_is_enforced()을 실행해 아래
# 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_token_estimate_is_deterministic_and_context_limit_is_enforced() -> None:
    # OllamaClient()의 반환값을 client에 대입합니다.
    client = OllamaClient(_llm_settings(), transport=ScriptedTransport())
    # messages에 리스트(순서가 있고 수정 가능)을 대입합니다.
    messages = [Message("system", "abcd"), Message("user", "한글")]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert client.count_tokens(messages) == 138

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="16K"):
        # client.complete()을 호출해 작업을 수행합니다.
        client.complete(
            messages=[Message("user", "가" * 50_000)],
            timeout_s=1,
            ctx=_context(),
        )


# pytest가 test_empty_prompt_is_rejected_and_missing_duration_uses_clock()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_empty_prompt_is_rejected_and_missing_duration_uses_clock() -> None:
    # OllamaClient()의 반환값을 client에 대입합니다.
    client = OllamaClient(
        _llm_settings(),
        transport=ScriptedTransport(_chat_response(total_duration=None)),
    )
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="메시지"):
        # client.complete()을 호출해 작업을 수행합니다.
        client.complete(messages=[], timeout_s=1, ctx=_context())

    # client.complete()의 반환값을 response에 대입합니다.
    response = client.complete(
        messages=[Message("user", "지연시간")],
        timeout_s=1,
        ctx=_context(),
        temperature=0.1,
        max_output_tokens=10,
    )
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response.usage.latency_ms == 0


# pytest가 test_client_defensively_rejects_non_loopback_settings_copy()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_client_defensively_rejects_non_loopback_settings_copy() -> None:
    # _llm_settings().model_copy()의 반환값을 unsafe에 대입합니다.
    unsafe = _llm_settings().model_copy(update={"base_url": "http://example.com"})

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="loopback"):
        # OllamaClient()을 호출해 작업을 수행합니다.
        OllamaClient(unsafe)

    # _llm_settings().model_copy()의 반환값을 non_local에 대입합니다.
    non_local = _llm_settings().model_copy(update={"local_only": False})
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="local_only"):
        # OllamaClient()을 호출해 작업을 수행합니다.
        OllamaClient(non_local)

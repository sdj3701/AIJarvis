# 파이썬 공부 | scripts/tests/unit/test_secrets.py
# secrets 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Tests for loading secrets without leaking their values."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.config.secrets import KeyringCredentialStore, SecretLoader
from app.core.errors import SecretsError

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase0

# TEST_SECRET에 문자열을 대입합니다.
TEST_SECRET = "sk-testAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


# FakeCredentialStore: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeCredentialStore:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: value, error.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, value: str | None = None, error: Exception | None = None) -> None:
        # 오른쪽 식을 계산한 값을 self.value에 대입합니다.
        self.value = value
        # 오른쪽 식을 계산한 값을 self.error에 대입합니다.
        self.error = error
        # self.calls에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.calls: list[tuple[str, str]] = []

    # get_password(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: service_name, username.
    # 반환 타입 힌트: str | None.
    def get_password(self, service_name: str, username: str) -> str | None:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.calls.append((service_name, username))
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.error is not None.
        if self.error is not None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise self.error
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.value


# RecordingMasker: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class RecordingMasker:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: error.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, error: Exception | None = None) -> None:
        # 오른쪽 식을 계산한 값을 self.error에 대입합니다.
        self.error = error
        # self.values에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.values: list[str] = []

    # register_secret(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: secret.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def register_secret(self, secret: str) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.error is not None.
        if self.error is not None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise self.error
        # 리스트 끝에 항목 하나를 추가합니다.
        self.values.append(secret)


# RecordingEvents: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class RecordingEvents:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: error.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, error: Exception | None = None) -> None:
        # 오른쪽 식을 계산한 값을 self.error에 대입합니다.
        self.error = error
        # self.items에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.items: list[tuple[str, Mapping[str, Any]]] = []

    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.error is not None.
        if self.error is not None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise self.error
        # 리스트 끝에 항목 하나를 추가합니다.
        self.items.append((event_type, dict(payload)))


# _loader(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path, dev_mode, credential, credential_error, masker, events.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: tuple[SecretLoader, FakeCredentialStore, RecordingMasker, RecordingEvents,
# Path].
def _loader(
    tmp_path: Path,
    *,
    dev_mode: bool,
    credential: str | None = None,
    credential_error: Exception | None = None,
    masker: RecordingMasker | None = None,
    events: RecordingEvents | None = None,
) -> tuple[SecretLoader, FakeCredentialStore, RecordingMasker, RecordingEvents, Path]:
    # FakeCredentialStore()의 반환값을 store에 대입합니다.
    store = FakeCredentialStore(credential, credential_error)
    # 오른쪽 식을 계산한 값을 actual_masker에 대입합니다.
    actual_masker = masker or RecordingMasker()
    # 오른쪽 식을 계산한 값을 actual_events에 대입합니다.
    actual_events = events or RecordingEvents()
    # 오른쪽 식을 계산한 값을 env_path에 대입합니다.
    env_path = tmp_path / ".env"
    # SecretLoader()의 반환값을 loader에 대입합니다.
    loader = SecretLoader(
        dev_mode=dev_mode,
        masker=actual_masker,
        events=actual_events,
        credential_store=store,
        env_path=env_path,
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return loader, store, actual_masker, actual_events, env_path


# pytest가 test_credential_manager_is_used_and_registered_for_masking()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_credential_manager_is_used_and_registered_for_masking(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (loader, store, masker, events, env_path)에 나누어 담습니다.
    loader, store, masker, events, env_path = _loader(
        tmp_path,
        dev_mode=True,
        credential=TEST_SECRET,
    )
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    env_path.write_text("JARVIS_LLM_API_KEY=ignored-development-value\n", encoding="utf-8")

    # loader.get_optional()의 반환값을 loaded에 대입합니다.
    loaded = loader.get_optional("llm_api_key")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert isinstance(loaded, SecretStr)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert loaded.get_secret_value() == TEST_SECRET
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert store.calls == [("jarvis", "llm_api_key")]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert masker.values == [TEST_SECRET]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.items == []


# pytest가 test_secret_repr_and_str_never_contain_value()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_secret_repr_and_str_never_contain_value(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, _, _, _)에 나누어 담습니다.
    loader, _, _, _, _ = _loader(tmp_path, dev_mode=False, credential=TEST_SECRET)

    # loader.require()의 반환값을 loaded에 대입합니다.
    loaded = loader.require("llm_api_key")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert TEST_SECRET not in repr(loaded)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert TEST_SECRET not in str(loaded)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert TEST_SECRET not in repr(loader)


# pytest가 test_production_mode_never_reads_dotenv()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_production_mode_never_reads_dotenv(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, masker, events, env_path)에 나누어 담습니다.
    loader, _, masker, events, env_path = _loader(tmp_path, dev_mode=False)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    env_path.write_text(f"JARVIS_LLM_API_KEY={TEST_SECRET}\n", encoding="utf-8")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert loader.get_optional("llm_api_key") is None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert masker.values == []
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.items == []


# pytest가 test_development_fallback_is_masked_and_emits_safe_event()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_development_fallback_is_masked_and_emits_safe_event(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (loader, store, masker, events, env_path)에 나누어 담습니다.
    loader, store, masker, events, env_path = _loader(tmp_path, dev_mode=True)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    env_path.write_text(f"JARVIS_LLM_API_KEY={TEST_SECRET}\n", encoding="utf-8")

    # loader.require()의 반환값을 loaded에 대입합니다.
    loaded = loader.require("llm_api_key")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert loaded.get_secret_value() == TEST_SECRET
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert store.calls == [("jarvis", "llm_api_key")]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert masker.values == [TEST_SECRET]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.items == [
        ("secrets.dev_fallback", {"key_name": "llm_api_key", "dev_mode": True})
    ]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert TEST_SECRET not in repr(events.items)


# pytest가 test_missing_optional_secret_is_allowed_in_phase_zero()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_missing_optional_secret_is_allowed_in_phase_zero(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, _, _, _)에 나누어 담습니다.
    loader, _, _, _, _ = _loader(tmp_path, dev_mode=True)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert loader.get_optional("llm_api_key") is None


# pytest가 test_require_raises_safe_error_for_missing_secret()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_require_raises_safe_error_for_missing_secret(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, _, _, _)에 나누어 담습니다.
    loader, _, _, _, _ = _loader(tmp_path, dev_mode=False)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SecretsError) as captured:
        # loader.require()을 호출해 작업을 수행합니다.
        loader.require("llm_api_key")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured.value.user_message
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "llm_api_key" in captured.value.detail["key_name"]


# pytest가 test_empty_credential_is_rejected_without_fallback()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_empty_credential_is_rejected_without_fallback(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, _, events, env_path)에 나누어 담습니다.
    loader, _, _, events, env_path = _loader(tmp_path, dev_mode=True, credential="")
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    env_path.write_text(f"JARVIS_LLM_API_KEY={TEST_SECRET}\n", encoding="utf-8")

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SecretsError):
        # loader.get_optional()을 호출해 작업을 수행합니다.
        loader.get_optional("llm_api_key")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.items == []


# pytest가 test_credential_backend_error_is_wrapped_without_original_message()을 실행해 아래
# 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_credential_backend_error_is_wrapped_without_original_message(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, _, _, _)에 나누어 담습니다.
    loader, _, _, _, _ = _loader(
        tmp_path,
        dev_mode=True,
        credential_error=RuntimeError(f"backend leaked {TEST_SECRET}"),
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SecretsError) as captured:
        # loader.get_optional()을 호출해 작업을 수행합니다.
        loader.get_optional("llm_api_key")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert TEST_SECRET not in str(captured.value)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert TEST_SECRET not in repr(captured.value.detail)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured.value.__context__ is None


# pytest가 test_masker_failure_cannot_leak_secret_through_exception()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_masker_failure_cannot_leak_secret_through_exception(tmp_path: Path) -> None:
    # RecordingMasker()의 반환값을 masker에 대입합니다.
    masker = RecordingMasker(RuntimeError(f"masking failed for {TEST_SECRET}"))
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, _, _, _)에 나누어 담습니다.
    loader, _, _, _, _ = _loader(
        tmp_path,
        dev_mode=False,
        credential=TEST_SECRET,
        masker=masker,
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SecretsError) as captured:
        # loader.get_optional()을 호출해 작업을 수행합니다.
        loader.get_optional("llm_api_key")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert TEST_SECRET not in str(captured.value)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert TEST_SECRET not in repr(captured.value.detail)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured.value.__context__ is None


# pytest가 test_event_failure_cannot_leak_secret_through_exception()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_event_failure_cannot_leak_secret_through_exception(tmp_path: Path) -> None:
    # RecordingEvents()의 반환값을 events에 대입합니다.
    events = RecordingEvents(RuntimeError(f"event failed for {TEST_SECRET}"))
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, _, _, env_path)에 나누어 담습니다.
    loader, _, _, _, env_path = _loader(
        tmp_path,
        dev_mode=True,
        events=events,
    )
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    env_path.write_text(f"JARVIS_LLM_API_KEY={TEST_SECRET}\n", encoding="utf-8")

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SecretsError) as captured:
        # loader.get_optional()을 호출해 작업을 수행합니다.
        loader.get_optional("llm_api_key")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert TEST_SECRET not in str(captured.value)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert TEST_SECRET not in repr(captured.value.detail)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured.value.__context__ is None


# pytest가 test_invalid_internal_key_name_is_rejected()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path, key_name.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("key_name", ["", "LLM_API_KEY", "../secret", "has-dash"])
def test_invalid_internal_key_name_is_rejected(tmp_path: Path, key_name: str) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (loader, store, _, _, _)에 나누어 담습니다.
    loader, store, _, _, _ = _loader(tmp_path, dev_mode=False)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SecretsError):
        # loader.get_optional()을 호출해 작업을 수행합니다.
        loader.get_optional(key_name)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert store.calls == []


# pytest가 test_duplicate_dotenv_key_is_rejected()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_duplicate_dotenv_key_is_rejected(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, _, _, env_path)에 나누어 담습니다.
    loader, _, _, _, env_path = _loader(tmp_path, dev_mode=True)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    env_path.write_text(
        f"JARVIS_LLM_API_KEY={TEST_SECRET}\nJARVIS_LLM_API_KEY=duplicate\n",
        encoding="utf-8",
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SecretsError):
        # loader.get_optional()을 호출해 작업을 수행합니다.
        loader.get_optional("llm_api_key")


# pytest가 test_malformed_dotenv_is_rejected_without_echoing_line()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_malformed_dotenv_is_rejected_without_echoing_line(tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 malformed에 대입합니다.
    # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
    malformed = f"not-an-assignment-{TEST_SECRET}"
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, _, _, env_path)에 나누어 담습니다.
    loader, _, _, _, env_path = _loader(tmp_path, dev_mode=True)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    env_path.write_text(malformed, encoding="utf-8")

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SecretsError) as captured:
        # loader.get_optional()을 호출해 작업을 수행합니다.
        loader.get_optional("llm_api_key")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert TEST_SECRET not in str(captured.value)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert TEST_SECRET not in repr(captured.value.detail)


# pytest가 test_quoted_dotenv_value_is_supported_without_expansion()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_quoted_dotenv_value_is_supported_without_expansion(tmp_path: Path) -> None:
    # quoted_secret에 문자열을 대입합니다.
    quoted_secret = "literal-$OTHER-secret"
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, masker, _, env_path)에 나누어 담습니다.
    loader, _, masker, _, env_path = _loader(tmp_path, dev_mode=True)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    env_path.write_text(f'JARVIS_SEARCH_API_KEY="{quoted_secret}"\n', encoding="utf-8")

    # loader.require()의 반환값을 loaded에 대입합니다.
    loaded = loader.require("search_api_key")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert loaded.get_secret_value() == quoted_secret
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert masker.values == [quoted_secret]


# pytest가 test_non_windows_keyring_backend_is_rejected()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_non_windows_keyring_backend_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # UnsupportedBackend: 관련 데이터와 동작을 한데 묶는 클래스입니다.
    class UnsupportedBackend:
        # 문법상 블록은 필요하지만 여기서는 아무 작업도 하지 않습니다.
        pass

    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr("keyring.get_keyring", UnsupportedBackend)
    # KeyringCredentialStore()의 반환값을 store에 대입합니다.
    store = KeyringCredentialStore()

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SecretsError):
        # store.get_password()을 호출해 작업을 수행합니다.
        store.get_password("jarvis", "llm_api_key")


# pytest가 test_windows_keyring_adapter_returns_value()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_windows_keyring_adapter_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    # WindowsBackend: 관련 데이터와 동작을 한데 묶는 클래스입니다.
    class WindowsBackend:
        # 문법상 블록은 필요하지만 여기서는 아무 작업도 하지 않습니다.
        pass

    # WindowsBackend.__module__에 문자열을 대입합니다.
    WindowsBackend.__module__ = "keyring.backends.Windows"
    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr("keyring.get_keyring", WindowsBackend)
    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr("keyring.get_password", lambda _service, _username: TEST_SECRET)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert KeyringCredentialStore().get_password("jarvis", "llm_api_key") == TEST_SECRET


# pytest가 test_keyring_backend_discovery_error_is_sanitized()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_keyring_backend_discovery_error_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    # fail_backend_discovery(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def fail_backend_discovery() -> None:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise RuntimeError(TEST_SECRET)

    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr("keyring.get_keyring", fail_backend_discovery)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SecretsError) as captured:
        # KeyringCredentialStore().get_password()을 호출해 작업을 수행합니다.
        KeyringCredentialStore().get_password("jarvis", "llm_api_key")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert TEST_SECRET not in str(captured.value)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured.value.__context__ is None


# pytest가 test_keyring_read_error_is_sanitized()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_keyring_read_error_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    # WindowsBackend: 관련 데이터와 동작을 한데 묶는 클래스입니다.
    class WindowsBackend:
        # 문법상 블록은 필요하지만 여기서는 아무 작업도 하지 않습니다.
        pass

    # fail_password_read(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: _service, _username.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def fail_password_read(_service: str, _username: str) -> None:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise RuntimeError(TEST_SECRET)

    # WindowsBackend.__module__에 문자열을 대입합니다.
    WindowsBackend.__module__ = "keyring.backends.Windows"
    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr("keyring.get_keyring", WindowsBackend)
    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr("keyring.get_password", fail_password_read)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SecretsError) as captured:
        # KeyringCredentialStore().get_password()을 호출해 작업을 수행합니다.
        KeyringCredentialStore().get_password("jarvis", "llm_api_key")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert TEST_SECRET not in str(captured.value)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured.value.__context__ is None


# pytest가 test_empty_dotenv_secret_is_rejected()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_empty_dotenv_secret_is_rejected(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, _, _, env_path)에 나누어 담습니다.
    loader, _, _, _, env_path = _loader(tmp_path, dev_mode=True)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    env_path.write_text("JARVIS_LLM_API_KEY=\n", encoding="utf-8")

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SecretsError):
        # loader.get_optional()을 호출해 작업을 수행합니다.
        loader.get_optional("llm_api_key")


# pytest가 test_oversized_dotenv_is_rejected()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_oversized_dotenv_is_rejected(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, _, _, env_path)에 나누어 담습니다.
    loader, _, _, _, env_path = _loader(tmp_path, dev_mode=True)
    # 바이트 데이터를 파일에 기록합니다.
    env_path.write_bytes(b"A" * (1024 * 1024 + 1))

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SecretsError):
        # loader.get_optional()을 호출해 작업을 수행합니다.
        loader.get_optional("llm_api_key")


# pytest가 test_non_utf8_dotenv_is_rejected()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_non_utf8_dotenv_is_rejected(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, _, _, env_path)에 나누어 담습니다.
    loader, _, _, _, env_path = _loader(tmp_path, dev_mode=True)
    # 바이트 데이터를 파일에 기록합니다.
    env_path.write_bytes(b"JARVIS_LLM_API_KEY=\xff")

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SecretsError):
        # loader.get_optional()을 호출해 작업을 수행합니다.
        loader.get_optional("llm_api_key")


# pytest가 test_unsafe_dotenv_value_syntax_is_rejected()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path, dotenv_text.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize(
    "dotenv_text",
    [
        "invalid-name=value\n",
        'JARVIS_LLM_API_KEY="unterminated\n',
        'JARVIS_LLM_API_KEY="unsupported\\n-escape"\n',
        'JARVIS_LLM_API_KEY="embedded\"quote"\n',
        'JARVIS_LLM_API_KEY="trailing\\"\n',
    ],
)
def test_unsafe_dotenv_value_syntax_is_rejected(tmp_path: Path, dotenv_text: str) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, _, _, env_path)에 나누어 담습니다.
    loader, _, _, _, env_path = _loader(tmp_path, dev_mode=True)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    env_path.write_text(dotenv_text, encoding="utf-8")

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SecretsError):
        # loader.get_optional()을 호출해 작업을 수행합니다.
        loader.get_optional("llm_api_key")


# pytest가 test_dotenv_comments_single_quotes_and_escaped_backslashes()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_dotenv_comments_single_quotes_and_escaped_backslashes(tmp_path: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (loader, _, masker, _, env_path)에 나누어 담습니다.
    loader, _, masker, _, env_path = _loader(tmp_path, dev_mode=True)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    env_path.write_text(
        "# development only\n"
        "JARVIS_SEARCH_API_KEY='single-quoted'\n"
        'JARVIS_LLM_API_KEY="escaped\\\\backslash"\n',
        encoding="utf-8",
    )

    # loader.require()의 반환값을 search_secret에 대입합니다.
    search_secret = loader.require("search_api_key")
    # loader.require()의 반환값을 llm_secret에 대입합니다.
    llm_secret = loader.require("llm_api_key")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert search_secret.get_secret_value() == "single-quoted"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert llm_secret.get_secret_value() == "escaped\\backslash"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert masker.values == ["single-quoted", "escaped\\backslash"]

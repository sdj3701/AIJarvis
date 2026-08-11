"""Tests for loading secrets without leaking their values."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.config.secrets import KeyringCredentialStore, SecretLoader
from app.core.errors import SecretsError

pytestmark = pytest.mark.phase0

TEST_SECRET = "sk-testAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


class FakeCredentialStore:
    def __init__(self, value: str | None = None, error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def get_password(self, service_name: str, username: str) -> str | None:
        self.calls.append((service_name, username))
        if self.error is not None:
            raise self.error
        return self.value


class RecordingMasker:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.values: list[str] = []

    def register_secret(self, secret: str) -> None:
        if self.error is not None:
            raise self.error
        self.values.append(secret)


class RecordingEvents:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.items: list[tuple[str, Mapping[str, Any]]] = []

    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self.error is not None:
            raise self.error
        self.items.append((event_type, dict(payload)))


def _loader(
    tmp_path: Path,
    *,
    dev_mode: bool,
    credential: str | None = None,
    credential_error: Exception | None = None,
    masker: RecordingMasker | None = None,
    events: RecordingEvents | None = None,
) -> tuple[SecretLoader, FakeCredentialStore, RecordingMasker, RecordingEvents, Path]:
    store = FakeCredentialStore(credential, credential_error)
    actual_masker = masker or RecordingMasker()
    actual_events = events or RecordingEvents()
    env_path = tmp_path / ".env"
    loader = SecretLoader(
        dev_mode=dev_mode,
        masker=actual_masker,
        events=actual_events,
        credential_store=store,
        env_path=env_path,
    )
    return loader, store, actual_masker, actual_events, env_path


def test_credential_manager_is_used_and_registered_for_masking(tmp_path: Path) -> None:
    loader, store, masker, events, env_path = _loader(
        tmp_path,
        dev_mode=True,
        credential=TEST_SECRET,
    )
    env_path.write_text("JARVIS_LLM_API_KEY=ignored-development-value\n", encoding="utf-8")

    loaded = loader.get_optional("llm_api_key")

    assert isinstance(loaded, SecretStr)
    assert loaded.get_secret_value() == TEST_SECRET
    assert store.calls == [("jarvis", "llm_api_key")]
    assert masker.values == [TEST_SECRET]
    assert events.items == []


def test_secret_repr_and_str_never_contain_value(tmp_path: Path) -> None:
    loader, _, _, _, _ = _loader(tmp_path, dev_mode=False, credential=TEST_SECRET)

    loaded = loader.require("llm_api_key")

    assert TEST_SECRET not in repr(loaded)
    assert TEST_SECRET not in str(loaded)
    assert TEST_SECRET not in repr(loader)


def test_production_mode_never_reads_dotenv(tmp_path: Path) -> None:
    loader, _, masker, events, env_path = _loader(tmp_path, dev_mode=False)
    env_path.write_text(f"JARVIS_LLM_API_KEY={TEST_SECRET}\n", encoding="utf-8")

    assert loader.get_optional("llm_api_key") is None
    assert masker.values == []
    assert events.items == []


def test_development_fallback_is_masked_and_emits_safe_event(tmp_path: Path) -> None:
    loader, store, masker, events, env_path = _loader(tmp_path, dev_mode=True)
    env_path.write_text(f"JARVIS_LLM_API_KEY={TEST_SECRET}\n", encoding="utf-8")

    loaded = loader.require("llm_api_key")

    assert loaded.get_secret_value() == TEST_SECRET
    assert store.calls == [("jarvis", "llm_api_key")]
    assert masker.values == [TEST_SECRET]
    assert events.items == [
        ("secrets.dev_fallback", {"key_name": "llm_api_key", "dev_mode": True})
    ]
    assert TEST_SECRET not in repr(events.items)


def test_missing_optional_secret_is_allowed_in_phase_zero(tmp_path: Path) -> None:
    loader, _, _, _, _ = _loader(tmp_path, dev_mode=True)

    assert loader.get_optional("llm_api_key") is None


def test_require_raises_safe_error_for_missing_secret(tmp_path: Path) -> None:
    loader, _, _, _, _ = _loader(tmp_path, dev_mode=False)

    with pytest.raises(SecretsError) as captured:
        loader.require("llm_api_key")

    assert captured.value.user_message
    assert "llm_api_key" in captured.value.detail["key_name"]


def test_empty_credential_is_rejected_without_fallback(tmp_path: Path) -> None:
    loader, _, _, events, env_path = _loader(tmp_path, dev_mode=True, credential="")
    env_path.write_text(f"JARVIS_LLM_API_KEY={TEST_SECRET}\n", encoding="utf-8")

    with pytest.raises(SecretsError):
        loader.get_optional("llm_api_key")

    assert events.items == []


def test_credential_backend_error_is_wrapped_without_original_message(tmp_path: Path) -> None:
    loader, _, _, _, _ = _loader(
        tmp_path,
        dev_mode=True,
        credential_error=RuntimeError(f"backend leaked {TEST_SECRET}"),
    )

    with pytest.raises(SecretsError) as captured:
        loader.get_optional("llm_api_key")

    assert TEST_SECRET not in str(captured.value)
    assert TEST_SECRET not in repr(captured.value.detail)
    assert captured.value.__context__ is None


def test_masker_failure_cannot_leak_secret_through_exception(tmp_path: Path) -> None:
    masker = RecordingMasker(RuntimeError(f"masking failed for {TEST_SECRET}"))
    loader, _, _, _, _ = _loader(
        tmp_path,
        dev_mode=False,
        credential=TEST_SECRET,
        masker=masker,
    )

    with pytest.raises(SecretsError) as captured:
        loader.get_optional("llm_api_key")

    assert TEST_SECRET not in str(captured.value)
    assert TEST_SECRET not in repr(captured.value.detail)
    assert captured.value.__context__ is None


def test_event_failure_cannot_leak_secret_through_exception(tmp_path: Path) -> None:
    events = RecordingEvents(RuntimeError(f"event failed for {TEST_SECRET}"))
    loader, _, _, _, env_path = _loader(
        tmp_path,
        dev_mode=True,
        events=events,
    )
    env_path.write_text(f"JARVIS_LLM_API_KEY={TEST_SECRET}\n", encoding="utf-8")

    with pytest.raises(SecretsError) as captured:
        loader.get_optional("llm_api_key")

    assert TEST_SECRET not in str(captured.value)
    assert TEST_SECRET not in repr(captured.value.detail)
    assert captured.value.__context__ is None


@pytest.mark.parametrize("key_name", ["", "LLM_API_KEY", "../secret", "has-dash"])
def test_invalid_internal_key_name_is_rejected(tmp_path: Path, key_name: str) -> None:
    loader, store, _, _, _ = _loader(tmp_path, dev_mode=False)

    with pytest.raises(SecretsError):
        loader.get_optional(key_name)

    assert store.calls == []


def test_duplicate_dotenv_key_is_rejected(tmp_path: Path) -> None:
    loader, _, _, _, env_path = _loader(tmp_path, dev_mode=True)
    env_path.write_text(
        f"JARVIS_LLM_API_KEY={TEST_SECRET}\nJARVIS_LLM_API_KEY=duplicate\n",
        encoding="utf-8",
    )

    with pytest.raises(SecretsError):
        loader.get_optional("llm_api_key")


def test_malformed_dotenv_is_rejected_without_echoing_line(tmp_path: Path) -> None:
    malformed = f"not-an-assignment-{TEST_SECRET}"
    loader, _, _, _, env_path = _loader(tmp_path, dev_mode=True)
    env_path.write_text(malformed, encoding="utf-8")

    with pytest.raises(SecretsError) as captured:
        loader.get_optional("llm_api_key")

    assert TEST_SECRET not in str(captured.value)
    assert TEST_SECRET not in repr(captured.value.detail)


def test_quoted_dotenv_value_is_supported_without_expansion(tmp_path: Path) -> None:
    quoted_secret = "literal-$OTHER-secret"
    loader, _, masker, _, env_path = _loader(tmp_path, dev_mode=True)
    env_path.write_text(f'JARVIS_SEARCH_API_KEY="{quoted_secret}"\n', encoding="utf-8")

    loaded = loader.require("search_api_key")

    assert loaded.get_secret_value() == quoted_secret
    assert masker.values == [quoted_secret]


def test_non_windows_keyring_backend_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    class UnsupportedBackend:
        pass

    monkeypatch.setattr("keyring.get_keyring", UnsupportedBackend)
    store = KeyringCredentialStore()

    with pytest.raises(SecretsError):
        store.get_password("jarvis", "llm_api_key")


def test_windows_keyring_adapter_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    class WindowsBackend:
        pass

    WindowsBackend.__module__ = "keyring.backends.Windows"
    monkeypatch.setattr("keyring.get_keyring", WindowsBackend)
    monkeypatch.setattr("keyring.get_password", lambda _service, _username: TEST_SECRET)

    assert KeyringCredentialStore().get_password("jarvis", "llm_api_key") == TEST_SECRET


def test_keyring_backend_discovery_error_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_backend_discovery() -> None:
        raise RuntimeError(TEST_SECRET)

    monkeypatch.setattr("keyring.get_keyring", fail_backend_discovery)

    with pytest.raises(SecretsError) as captured:
        KeyringCredentialStore().get_password("jarvis", "llm_api_key")

    assert TEST_SECRET not in str(captured.value)
    assert captured.value.__context__ is None


def test_keyring_read_error_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    class WindowsBackend:
        pass

    def fail_password_read(_service: str, _username: str) -> None:
        raise RuntimeError(TEST_SECRET)

    WindowsBackend.__module__ = "keyring.backends.Windows"
    monkeypatch.setattr("keyring.get_keyring", WindowsBackend)
    monkeypatch.setattr("keyring.get_password", fail_password_read)

    with pytest.raises(SecretsError) as captured:
        KeyringCredentialStore().get_password("jarvis", "llm_api_key")

    assert TEST_SECRET not in str(captured.value)
    assert captured.value.__context__ is None


def test_empty_dotenv_secret_is_rejected(tmp_path: Path) -> None:
    loader, _, _, _, env_path = _loader(tmp_path, dev_mode=True)
    env_path.write_text("JARVIS_LLM_API_KEY=\n", encoding="utf-8")

    with pytest.raises(SecretsError):
        loader.get_optional("llm_api_key")


def test_oversized_dotenv_is_rejected(tmp_path: Path) -> None:
    loader, _, _, _, env_path = _loader(tmp_path, dev_mode=True)
    env_path.write_bytes(b"A" * (1024 * 1024 + 1))

    with pytest.raises(SecretsError):
        loader.get_optional("llm_api_key")


def test_non_utf8_dotenv_is_rejected(tmp_path: Path) -> None:
    loader, _, _, _, env_path = _loader(tmp_path, dev_mode=True)
    env_path.write_bytes(b"JARVIS_LLM_API_KEY=\xff")

    with pytest.raises(SecretsError):
        loader.get_optional("llm_api_key")


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
    loader, _, _, _, env_path = _loader(tmp_path, dev_mode=True)
    env_path.write_text(dotenv_text, encoding="utf-8")

    with pytest.raises(SecretsError):
        loader.get_optional("llm_api_key")


def test_dotenv_comments_single_quotes_and_escaped_backslashes(tmp_path: Path) -> None:
    loader, _, masker, _, env_path = _loader(tmp_path, dev_mode=True)
    env_path.write_text(
        "# development only\n"
        "JARVIS_SEARCH_API_KEY='single-quoted'\n"
        'JARVIS_LLM_API_KEY="escaped\\\\backslash"\n',
        encoding="utf-8",
    )

    search_secret = loader.require("search_api_key")
    llm_secret = loader.require("llm_api_key")

    assert search_secret.get_secret_value() == "single-quoted"
    assert llm_secret.get_secret_value() == "escaped\\backslash"
    assert masker.values == ["single-quoted", "escaped\\backslash"]

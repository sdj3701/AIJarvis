"""Load secrets from Windows Credential Manager with a development-only fallback."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

import keyring
from pydantic import SecretStr

from app.core.errors import SecretsError

DEFAULT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
_KEY_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_MAX_ENV_BYTES = 1024 * 1024
_MAX_SECRET_CHARS = 16 * 1024


class CredentialStore(Protocol):
    """Small interface around a secure operating-system credential store."""

    def get_password(self, service_name: str, username: str) -> str | None: ...


class SecretMasker(Protocol):
    """Registers exact values that must be masked from later output."""

    def register_secret(self, secret: str) -> None: ...


class EventSink(Protocol):
    """Accepts structured events without secret values."""

    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


class KeyringCredentialStore:
    """Use only keyring's Windows Credential Manager backend."""

    def get_password(self, service_name: str, username: str) -> str | None:
        backend: Any = None
        failure_type: str | None = None
        try:
            backend = keyring.get_keyring()
        except Exception as error:  # keyring backends can raise platform-specific errors
            failure_type = type(error).__name__

        if failure_type is not None:
            raise SecretsError(
                "Windows 자격 증명 관리자 백엔드를 확인할 수 없습니다.",
                {"error_type": failure_type},
            )

        backend_type = type(backend)
        if not backend_type.__module__.startswith("keyring.backends.Windows"):
            raise SecretsError(
                "Windows 자격 증명 관리자 백엔드만 사용할 수 있습니다.",
                {
                    "backend_module": backend_type.__module__,
                    "backend_type": backend_type.__name__,
                },
            )

        result: str | None = None
        failure_type = None
        try:
            result = keyring.get_password(service_name, username)
        except Exception as error:  # never copy backend messages into our exception
            failure_type = type(error).__name__

        if failure_type is not None:
            raise SecretsError(
                "Windows 자격 증명 관리자에서 시크릿을 읽을 수 없습니다.",
                {"key_name": username, "error_type": failure_type},
            )
        return result


class SecretLoader:
    """Read optional or required secrets without exposing their raw values."""

    SERVICE_NAME = "jarvis"

    def __init__(
        self,
        *,
        dev_mode: bool,
        masker: SecretMasker,
        events: EventSink,
        credential_store: CredentialStore | None = None,
        env_path: Path = DEFAULT_ENV_PATH,
    ) -> None:
        self._dev_mode = dev_mode
        self._masker = masker
        self._events = events
        self._credential_store = (
            credential_store if credential_store is not None else KeyringCredentialStore()
        )
        self._env_path = Path(env_path)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(dev_mode={self._dev_mode!r}, "
            f"env_path={str(self._env_path)!r})"
        )

    @staticmethod
    def environment_name(key_name: str) -> str:
        """Map a Credential Manager username to its development .env key."""
        _validate_key_name(key_name)
        return f"JARVIS_{key_name.upper()}"

    def get_optional(self, key_name: str) -> SecretStr | None:
        """Return a secret when configured; absence is valid during Phase 0."""
        env_name = self.environment_name(key_name)
        credential = self._get_credential(key_name)
        if credential is not None:
            if credential == "":
                raise SecretsError(
                    "Windows 자격 증명 관리자에 빈 시크릿이 저장되어 있습니다.",
                    {"key_name": key_name, "source": "credential_manager"},
                )
            return self._register_and_wrap(credential, key_name=key_name)

        if not self._dev_mode:
            return None

        fallback = _read_dotenv_value(self._env_path, env_name)
        if fallback is None:
            return None
        wrapped = self._register_and_wrap(fallback, key_name=key_name)
        self._emit_dev_fallback(key_name)
        return wrapped

    def require(self, key_name: str) -> SecretStr:
        """Return a configured secret or raise a safe, user-facing error."""
        secret = self.get_optional(key_name)
        if secret is None:
            raise SecretsError(
                "필요한 시크릿이 설정되어 있지 않습니다.",
                {"key_name": key_name},
            )
        return secret

    def _get_credential(self, key_name: str) -> str | None:
        result: str | None = None
        failure_type: str | None = None
        try:
            result = self._credential_store.get_password(self.SERVICE_NAME, key_name)
        except SecretsError:
            raise
        except Exception as error:
            failure_type = type(error).__name__

        if failure_type is not None:
            raise SecretsError(
                "Windows 자격 증명 관리자에서 시크릿을 읽을 수 없습니다.",
                {"key_name": key_name, "error_type": failure_type},
            )
        return result

    def _register_and_wrap(self, raw_secret: str, *, key_name: str) -> SecretStr:
        if not raw_secret or len(raw_secret) > _MAX_SECRET_CHARS or "\x00" in raw_secret:
            raise SecretsError(
                "시크릿 값의 형식이 올바르지 않습니다.",
                {"key_name": key_name, "reason": "invalid_secret_value"},
            )

        failure_type: str | None = None
        try:
            self._masker.register_secret(raw_secret)
        except Exception as error:
            failure_type = type(error).__name__

        if failure_type is not None:
            raise SecretsError(
                "시크릿 마스킹 등록에 실패했습니다.",
                {"key_name": key_name, "error_type": failure_type},
            )
        return SecretStr(raw_secret)

    def _emit_dev_fallback(self, key_name: str) -> None:
        failure_type: str | None = None
        try:
            self._events.emit(
                "secrets.dev_fallback",
                {"key_name": key_name, "dev_mode": True},
            )
        except Exception as error:
            failure_type = type(error).__name__

        if failure_type is not None:
            raise SecretsError(
                "개발용 시크릿 폴백 이벤트를 기록할 수 없습니다.",
                {"key_name": key_name, "error_type": failure_type},
            )


def _validate_key_name(key_name: str) -> None:
    if not _KEY_NAME_PATTERN.fullmatch(key_name):
        raise SecretsError(
            "시크릿 키 이름이 올바르지 않습니다.",
            {"reason": "invalid_key_name"},
        )


def _read_dotenv_value(path: Path, wanted_name: str) -> str | None:
    if not path.exists():
        return None

    lines: list[str] | None = None
    failure_type: str | None = None
    try:
        if path.stat().st_size > _MAX_ENV_BYTES:
            raise ValueError("dotenv_too_large")
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError, ValueError) as error:
        failure_type = type(error).__name__

    if failure_type is not None or lines is None:
        raise SecretsError(
            "개발용 .env 파일을 안전하게 읽을 수 없습니다.",
            {"file": str(path), "error_type": failure_type or "UnknownError"},
        )

    found = False
    found_value: str | None = None
    for line_number, original_line in enumerate(lines, start=1):
        line = original_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise _dotenv_error(path, line_number, "missing_assignment")
        raw_name, raw_value = line.split("=", maxsplit=1)
        name = raw_name.strip()
        if not _ENV_NAME_PATTERN.fullmatch(name):
            raise _dotenv_error(path, line_number, "invalid_name")
        value = _parse_dotenv_value(path, line_number, raw_value)
        if name == wanted_name:
            if found:
                raise _dotenv_error(path, line_number, "duplicate_key")
            found = True
            found_value = value
    return found_value


def _parse_dotenv_value(path: Path, line_number: int, raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""
    if value[0] not in {"'", '"'}:
        if "\x00" in value:
            raise _dotenv_error(path, line_number, "invalid_value")
        return value

    quote = value[0]
    if len(value) < 2 or value[-1] != quote:
        raise _dotenv_error(path, line_number, "unterminated_quote")
    inner = value[1:-1]
    if quote == "'":
        if "'" in inner or "\x00" in inner:
            raise _dotenv_error(path, line_number, "invalid_quoted_value")
        return inner

    parsed: list[str] = []
    escaped = False
    for character in inner:
        if escaped:
            if character not in {'"', "\\"}:
                raise _dotenv_error(path, line_number, "unsupported_escape")
            parsed.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"' or character == "\x00":
            raise _dotenv_error(path, line_number, "invalid_quoted_value")
        else:
            parsed.append(character)
    if escaped:
        raise _dotenv_error(path, line_number, "unterminated_escape")
    return "".join(parsed)


def _dotenv_error(path: Path, line_number: int, reason: str) -> SecretsError:
    return SecretsError(
        "개발용 .env 파일 형식이 올바르지 않습니다.",
        {"file": str(path), "line": line_number, "reason": reason},
    )

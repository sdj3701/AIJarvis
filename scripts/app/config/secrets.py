# 파이썬 공부 | scripts/app/config/secrets.py
# Windows 자격 증명 저장소 등에서 비밀 설정 값을 읽습니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Load secrets from Windows Credential Manager with a development-only fallback."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

import keyring
from pydantic import SecretStr

from app.core.errors import SecretsError

# 오른쪽 식을 계산한 값을 DEFAULT_ENV_PATH에 대입합니다.
DEFAULT_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
# re.compile()의 반환값을 _KEY_NAME_PATTERN에 대입합니다.
_KEY_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# re.compile()의 반환값을 _ENV_NAME_PATTERN에 대입합니다.
_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
# 오른쪽 식을 계산한 값을 _MAX_ENV_BYTES에 대입합니다.
_MAX_ENV_BYTES = 1024 * 1024
# 오른쪽 식을 계산한 값을 _MAX_SECRET_CHARS에 대입합니다.
_MAX_SECRET_CHARS = 16 * 1024


# CredentialStore: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class CredentialStore(Protocol):
    """Small interface around a secure operating-system credential store."""

    # get_password(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: service_name, username.
    # 반환 타입 힌트: str | None.
    def get_password(self, service_name: str, username: str) -> str | None: ...


# SecretMasker: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class SecretMasker(Protocol):
    """Registers exact values that must be masked from later output."""

    # register_secret(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: secret.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def register_secret(self, secret: str) -> None: ...


# EventSink: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class EventSink(Protocol):
    """Accepts structured events without secret values."""

    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


# KeyringCredentialStore: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class KeyringCredentialStore:
    """Use only keyring's Windows Credential Manager backend."""

    # get_password(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: service_name, username.
    # 반환 타입 힌트: str | None.
    def get_password(self, service_name: str, username: str) -> str | None:
        # backend을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        backend: Any = None
        # failure_type을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        failure_type: str | None = None
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # keyring.get_keyring()의 반환값을 backend에 대입합니다.
            backend = keyring.get_keyring()
        # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except Exception as error:  # keyring backends can raise platform-specific errors
            # 오른쪽 식을 계산한 값을 failure_type에 대입합니다.
            failure_type = type(error).__name__

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: failure_type is not None.
        if failure_type is not None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise SecretsError(
                "Windows 자격 증명 관리자 백엔드를 확인할 수 없습니다.",
                {"error_type": failure_type},
            )

        # type()의 반환값을 backend_type에 대입합니다.
        backend_type = type(backend)
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not backend_type.__module__.startswith("keyring.backends.Windows"):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise SecretsError(
                "Windows 자격 증명 관리자 백엔드만 사용할 수 있습니다.",
                {
                    "backend_module": backend_type.__module__,
                    "backend_type": backend_type.__name__,
                },
            )

        # result을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        result: str | None = None
        # failure_type을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        failure_type = None
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # keyring.get_password()의 반환값을 result에 대입합니다.
            result = keyring.get_password(service_name, username)
        # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except Exception as error:  # never copy backend messages into our exception
            # 오른쪽 식을 계산한 값을 failure_type에 대입합니다.
            failure_type = type(error).__name__

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: failure_type is not None.
        if failure_type is not None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise SecretsError(
                "Windows 자격 증명 관리자에서 시크릿을 읽을 수 없습니다.",
                {"key_name": username, "error_type": failure_type},
            )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return result


# SecretLoader: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class SecretLoader:
    """Read optional or required secrets without exposing their raw values."""

    # SERVICE_NAME에 문자열을 대입합니다.
    SERVICE_NAME = "jarvis"

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: dev_mode, masker, events, credential_store, env_path.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        *,
        dev_mode: bool,
        masker: SecretMasker,
        events: EventSink,
        credential_store: CredentialStore | None = None,
        env_path: Path = DEFAULT_ENV_PATH,
    ) -> None:
        # 오른쪽 식을 계산한 값을 self._dev_mode에 대입합니다.
        self._dev_mode = dev_mode
        # 오른쪽 식을 계산한 값을 self._masker에 대입합니다.
        self._masker = masker
        # 오른쪽 식을 계산한 값을 self._events에 대입합니다.
        self._events = events
        # 오른쪽 식을 계산한 값을 self._credential_store에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        self._credential_store = (
            credential_store if credential_store is not None else KeyringCredentialStore()
        )
        # Path()의 반환값을 self._env_path에 대입합니다.
        self._env_path = Path(env_path)

    # __repr__(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    def __repr__(self) -> str:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
        return (
            f"{type(self).__name__}(dev_mode={self._dev_mode!r}, "
            f"env_path={str(self._env_path)!r})"
        )

    # environment_name(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: key_name.
    # 반환 타입 힌트: 문자열(str).
    # @staticmethod: self나 cls를 자동으로 받지 않습니다.
    @staticmethod
    def environment_name(key_name: str) -> str:
        """Map a Credential Manager username to its development .env key."""
        # _validate_key_name()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_key_name(key_name)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
        return f"JARVIS_{key_name.upper()}"

    # get_optional(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: key_name.
    # 반환 타입 힌트: SecretStr | None.
    def get_optional(self, key_name: str) -> SecretStr | None:
        """Return a secret when configured; absence is valid so the skeleton can boot.

        The raw value is registered with the masker before this method returns.
        """
        # self.environment_name()의 반환값을 env_name에 대입합니다.
        env_name = self.environment_name(key_name)
        # self._get_credential()의 반환값을 credential에 대입합니다.
        credential = self._get_credential(key_name)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: credential is not None.
        if credential is not None:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: credential == ''.
            if credential == "":
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise SecretsError(
                    "Windows 자격 증명 관리자에 빈 시크릿이 저장되어 있습니다.",
                    {"key_name": key_name, "source": "credential_manager"},
                )
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return self._register_and_wrap(credential, key_name=key_name)

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self._dev_mode.
        if not self._dev_mode:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None

        # _read_dotenv_value()의 반환값을 fallback에 대입합니다.
        fallback = _read_dotenv_value(self._env_path, env_name)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: fallback is None.
        if fallback is None:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None
        # self._register_and_wrap()의 반환값을 wrapped에 대입합니다.
        wrapped = self._register_and_wrap(fallback, key_name=key_name)
        # self._emit_dev_fallback()을 호출해 작업을 수행합니다.
        self._emit_dev_fallback(key_name)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return wrapped

    # require(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: key_name.
    # 반환 타입 힌트: SecretStr.
    def require(self, key_name: str) -> SecretStr:
        """Return a configured secret or raise a safe, user-facing error."""
        # self.get_optional()의 반환값을 secret에 대입합니다.
        secret = self.get_optional(key_name)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: secret is None.
        if secret is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise SecretsError(
                "필요한 시크릿이 설정되어 있지 않습니다.",
                {"key_name": key_name},
            )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return secret

    # _get_credential(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: key_name.
    # 반환 타입 힌트: str | None.
    def _get_credential(self, key_name: str) -> str | None:
        # result을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        result: str | None = None
        # failure_type을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        failure_type: str | None = None
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # self._credential_store.get_password()의 반환값을 result에 대입합니다.
            result = self._credential_store.get_password(self.SERVICE_NAME, key_name)
        # SecretsError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except SecretsError:
            # 현재 예외를 다시 발생시켜 호출한 쪽으로 전달합니다.
            raise
        # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except Exception as error:
            # 오른쪽 식을 계산한 값을 failure_type에 대입합니다.
            failure_type = type(error).__name__

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: failure_type is not None.
        if failure_type is not None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise SecretsError(
                "Windows 자격 증명 관리자에서 시크릿을 읽을 수 없습니다.",
                {"key_name": key_name, "error_type": failure_type},
            )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return result

    # _register_and_wrap(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: raw_secret, key_name.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: SecretStr.
    def _register_and_wrap(self, raw_secret: str, *, key_name: str) -> SecretStr:
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not raw_secret or len(raw_secret) > _MAX_SECRET_CHARS or "\x00" in raw_secret:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise SecretsError(
                "시크릿 값의 형식이 올바르지 않습니다.",
                {"key_name": key_name, "reason": "invalid_secret_value"},
            )

        # failure_type을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        failure_type: str | None = None
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # self._masker.register_secret()을 호출해 작업을 수행합니다.
            self._masker.register_secret(raw_secret)
        # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except Exception as error:
            # 오른쪽 식을 계산한 값을 failure_type에 대입합니다.
            failure_type = type(error).__name__

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: failure_type is not None.
        if failure_type is not None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise SecretsError(
                "시크릿 마스킹 등록에 실패했습니다.",
                {"key_name": key_name, "error_type": failure_type},
            )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return SecretStr(raw_secret)

    # _emit_dev_fallback(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: key_name.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _emit_dev_fallback(self, key_name: str) -> None:
        # failure_type을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        failure_type: str | None = None
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
            self._events.emit(
                "secrets.dev_fallback",
                {"key_name": key_name, "dev_mode": True},
            )
        # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except Exception as error:
            # 오른쪽 식을 계산한 값을 failure_type에 대입합니다.
            failure_type = type(error).__name__

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: failure_type is not None.
        if failure_type is not None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise SecretsError(
                "개발용 시크릿 폴백 이벤트를 기록할 수 없습니다.",
                {"key_name": key_name, "error_type": failure_type},
            )


# _validate_key_name(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: key_name.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_key_name(key_name: str) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not _KEY_NAME_PATTERN.fullmatch(key_name).
    if not _KEY_NAME_PATTERN.fullmatch(key_name):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise SecretsError(
            "시크릿 키 이름이 올바르지 않습니다.",
            {"reason": "invalid_key_name"},
        )


# _read_dotenv_value(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, wanted_name.
# 반환 타입 힌트: str | None.
def _read_dotenv_value(path: Path, wanted_name: str) -> str | None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not path.exists().
    if not path.exists():
        # None을 반환하고 이 함수의 실행을 끝냅니다.
        return None

    # lines을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    lines: list[str] | None = None
    # failure_type을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    failure_type: str | None = None
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: path.stat().st_size > _MAX_ENV_BYTES.
        if path.stat().st_size > _MAX_ENV_BYTES:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("dotenv_too_large")
        # 아래 함수()의 반환값을 lines에 대입합니다.
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    # (OSError, UnicodeError, ValueError)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
    # 담깁니다.
    except (OSError, UnicodeError, ValueError) as error:
        # 오른쪽 식을 계산한 값을 failure_type에 대입합니다.
        failure_type = type(error).__name__

    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: failure_type is not None or lines is None.
    if failure_type is not None or lines is None:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise SecretsError(
            "개발용 .env 파일을 안전하게 읽을 수 없습니다.",
            {"file": str(path), "error_type": failure_type or "UnknownError"},
        )

    # found을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    found = False
    # found_value을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    found_value: str | None = None
    # for 반복문: 대상의 항목을 하나씩 (line_number, original_line)에 대입하며 아래 블록을
    # 실행합니다.
    for line_number, original_line in enumerate(lines, start=1):
        # original_line.strip()의 반환값을 line에 대입합니다.
        line = original_line.strip()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not line or line.startswith('#').
        if not line or line.startswith("#"):
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: '=' not in line.
        if "=" not in line:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise _dotenv_error(path, line_number, "missing_assignment")
        # 언패킹: 오른쪽 결과를 순서대로 (raw_name, raw_value)에 나누어 담습니다.
        raw_name, raw_value = line.split("=", maxsplit=1)
        # raw_name.strip()의 반환값을 name에 대입합니다.
        name = raw_name.strip()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not _ENV_NAME_PATTERN.fullmatch(name).
        if not _ENV_NAME_PATTERN.fullmatch(name):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise _dotenv_error(path, line_number, "invalid_name")
        # _parse_dotenv_value()의 반환값을 value에 대입합니다.
        value = _parse_dotenv_value(path, line_number, raw_value)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: name == wanted_name.
        if name == wanted_name:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: found.
            if found:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise _dotenv_error(path, line_number, "duplicate_key")
            # found을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
            found = True
            # 오른쪽 식을 계산한 값을 found_value에 대입합니다.
            found_value = value
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return found_value


# _parse_dotenv_value(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, line_number, raw_value.
# 반환 타입 힌트: 문자열(str).
def _parse_dotenv_value(path: Path, line_number: int, raw_value: str) -> str:
    # raw_value.strip()의 반환값을 value에 대입합니다.
    value = raw_value.strip()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not value.
    if not value:
        # ''을 반환하고 이 함수의 실행을 끝냅니다.
        return ""
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: value[0] not in {"'", '"'}.
    if value[0] not in {"'", '"'}:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: '\x00' in value.
        if "\x00" in value:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise _dotenv_error(path, line_number, "invalid_value")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return value

    # 오른쪽 식을 계산한 값을 quote에 대입합니다.
    quote = value[0]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(value) < 2 or value[-1] != quote.
    if len(value) < 2 or value[-1] != quote:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise _dotenv_error(path, line_number, "unterminated_quote")
    # 오른쪽 식을 계산한 값을 inner에 대입합니다.
    # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
    inner = value[1:-1]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: quote == "'".
    if quote == "'":
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: "'" in inner or '\x00' in inner.
        if "'" in inner or "\x00" in inner:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise _dotenv_error(path, line_number, "invalid_quoted_value")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return inner

    # parsed에 리스트(순서가 있고 수정 가능)을 대입합니다.
    parsed: list[str] = []
    # escaped을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    escaped = False
    # for 반복문: 대상의 항목을 하나씩 character에 대입하며 아래 블록을 실행합니다.
    for character in inner:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: escaped.
        if escaped:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: character not in {'"', '\\'}.
            if character not in {'"', "\\"}:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise _dotenv_error(path, line_number, "unsupported_escape")
            # 리스트 끝에 항목 하나를 추가합니다.
            parsed.append(character)
            # escaped을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
            escaped = False
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: character == '\\'.
        elif character == "\\":
            # escaped을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
            escaped = True
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: character == '"' or character ==
        # '\x00'.
        elif character == '"' or character == "\x00":
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise _dotenv_error(path, line_number, "invalid_quoted_value")
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # 리스트 끝에 항목 하나를 추가합니다.
            parsed.append(character)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: escaped.
    if escaped:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise _dotenv_error(path, line_number, "unterminated_escape")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return "".join(parsed)


# _dotenv_error(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, line_number, reason.
# 반환 타입 힌트: SecretsError.
def _dotenv_error(path: Path, line_number: int, reason: str) -> SecretsError:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return SecretsError(
        "개발용 .env 파일 형식이 올바르지 않습니다.",
        {"file": str(path), "line": line_number, "reason": reason},
    )

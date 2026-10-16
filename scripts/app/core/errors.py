# 파이썬 공부 | scripts/app/core/errors.py
# 앱에서 사용하는 오류 종류와 사용자에게 보여 줄 오류 정보를 정의합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Application exceptions with safe user-facing messages."""

from __future__ import annotations

from collections.abc import Mapping
from enum import IntEnum
from typing import Any


# JarvisError: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: Exception.
class JarvisError(Exception):
    """Base exception that separates user text from diagnostic details."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: user_message, detail.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        user_message: str,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        # super().__init__()을 호출해 작업을 수행합니다.
        super().__init__(user_message)
        # 오른쪽 식을 계산한 값을 self.user_message에 대입합니다.
        self.user_message = user_message
        # dict()의 반환값을 self.detail에 대입합니다.
        self.detail = dict(detail or {})


# ConfigError: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: JarvisError.
class ConfigError(JarvisError):
    """A configuration file is missing, malformed, or unsafe."""


# SecretsError: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: JarvisError.
class SecretsError(JarvisError):
    """A secret is missing or its secure storage cannot be accessed."""


# PrivacyBlocked: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: JarvisError.
class PrivacyBlocked(JarvisError):
    """A privacy rule blocked a transmission or output channel."""


# PolicyDenied: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: JarvisError.
class PolicyDenied(JarvisError):
    """The requested operation is forbidden by the safety policy."""


# ApprovalRequired: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: JarvisError.
class ApprovalRequired(JarvisError):
    """Execution must pause until the caller obtains explicit approval."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: user_message, detail, verdict.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        user_message: str,
        detail: Mapping[str, Any] | None = None,
        *,
        verdict: Any = None,
    ) -> None:
        # super().__init__()을 호출해 작업을 수행합니다.
        super().__init__(user_message, detail)
        # 오른쪽 식을 계산한 값을 self.verdict에 대입합니다.
        self.verdict = verdict


# ApprovalMismatch: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: JarvisError.
class ApprovalMismatch(JarvisError):
    """An approval ticket is absent, expired, consumed, or mismatched."""


# BudgetExceeded: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: JarvisError.
class BudgetExceeded(JarvisError):
    """The configured daily or monthly external-service budget is exhausted."""


# PromptTooLong: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: JarvisError.
class PromptTooLong(JarvisError):
    """The protected prompt content cannot fit the configured context budget."""


# LLMError: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: JarvisError.
class LLMError(JarvisError):
    """Base class for model-provider failures."""


# LLMTimeout: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: LLMError.
class LLMTimeout(LLMError):
    """The model provider did not respond before its deadline."""


# LLMUnavailable: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: LLMError.
class LLMUnavailable(LLMError):
    """The configured local model runtime is unavailable."""


# LLMRateLimited: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: LLMError.
class LLMRateLimited(LLMError):
    """The model provider rejected the request due to rate limits."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: user_message, detail, retry_after.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        user_message: str,
        detail: Mapping[str, Any] | None = None,
        *,
        retry_after: float | None = None,
    ) -> None:
        # super().__init__()을 호출해 작업을 수행합니다.
        super().__init__(user_message, detail)
        # 오른쪽 식을 계산한 값을 self.retry_after에 대입합니다.
        self.retry_after = retry_after


# LLMAuthError: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: LLMError.
class LLMAuthError(LLMError):
    """The model provider rejected configured credentials."""


# LLMBadResponse: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: LLMError.
class LLMBadResponse(LLMError):
    """A provider response was malformed or violated its schema."""


# ToolError: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: JarvisError.
class ToolError(JarvisError):
    """Base class for tool lookup, validation, and execution failures."""


# ToolNotFound: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: ToolError.
class ToolNotFound(ToolError):
    """The requested tool is not registered."""


# ToolArgInvalid: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: ToolError.
class ToolArgInvalid(ToolError):
    """Tool arguments failed schema or safety validation."""


# ToolTimeout: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: ToolError.
class ToolTimeout(ToolError):
    """A managed tool exceeded its execution deadline."""


# ToolExecutionFailed: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: ToolError.
class ToolExecutionFailed(ToolError):
    """A tool process or in-process implementation failed."""


# MemoryError: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: JarvisError.
class MemoryError(JarvisError):
    """Base class for local memory-store failures."""


# MemoryCorrupted: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: MemoryError.
class MemoryCorrupted(MemoryError):
    """Stored memory failed an integrity check."""


# MemoryQuotaExceeded: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: MemoryError.
class MemoryQuotaExceeded(MemoryError):
    """The configured local memory quota is exhausted."""


# RecoveryError: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: JarvisError.
class RecoveryError(JarvisError):
    """Startup or checkpoint recovery could not complete safely."""


# ExitCode: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: IntEnum.
class ExitCode(IntEnum):
    # SUCCESS에 숫자 등 고정된 값을 대입합니다.
    SUCCESS = 0
    # UNHANDLED_ERROR에 숫자 등 고정된 값을 대입합니다.
    UNHANDLED_ERROR = 1
    # CONFIG_OR_SECRETS에 숫자 등 고정된 값을 대입합니다.
    CONFIG_OR_SECRETS = 2
    # POLICY_DENIED에 숫자 등 고정된 값을 대입합니다.
    POLICY_DENIED = 3
    # BUDGET_EXCEEDED에 숫자 등 고정된 값을 대입합니다.
    BUDGET_EXCEEDED = 4
    # DATA_OR_RECOVERY에 숫자 등 고정된 값을 대입합니다.
    DATA_OR_RECOVERY = 5
    # INTERRUPTED에 숫자 등 고정된 값을 대입합니다.
    INTERRUPTED = 130


# exit_code_for(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: error.
# 반환 타입 힌트: ExitCode.
def exit_code_for(error: BaseException) -> ExitCode:
    """Map a handled exception to the documented process exit code."""
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(error, KeyboardInterrupt |
    # InterruptedError).
    if isinstance(error, KeyboardInterrupt | InterruptedError):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ExitCode.INTERRUPTED
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(error, ConfigError |
    # SecretsError).
    if isinstance(error, ConfigError | SecretsError):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ExitCode.CONFIG_OR_SECRETS
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if isinstance(error, PrivacyBlocked | PolicyDenied | ApprovalRequired | ApprovalMismatch):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ExitCode.POLICY_DENIED
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(error, BudgetExceeded).
    if isinstance(error, BudgetExceeded):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ExitCode.BUDGET_EXCEEDED
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(error, MemoryCorrupted |
    # RecoveryError).
    if isinstance(error, MemoryCorrupted | RecoveryError):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ExitCode.DATA_OR_RECOVERY
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return ExitCode.UNHANDLED_ERROR

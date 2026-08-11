"""Application exceptions with safe user-facing messages."""

from __future__ import annotations

from collections.abc import Mapping
from enum import IntEnum
from typing import Any


class JarvisError(Exception):
    """Base exception that separates user text from diagnostic details."""

    def __init__(
        self,
        user_message: str,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = dict(detail or {})


class ConfigError(JarvisError):
    """A configuration file is missing, malformed, or unsafe."""


class SecretsError(JarvisError):
    """A secret is missing or its secure storage cannot be accessed."""


class PrivacyBlocked(JarvisError):
    """A privacy rule blocked a transmission or output channel."""


class PolicyDenied(JarvisError):
    """The requested operation is forbidden by the safety policy."""


class ApprovalRequired(JarvisError):
    """Execution must pause until the caller obtains explicit approval."""

    def __init__(
        self,
        user_message: str,
        detail: Mapping[str, Any] | None = None,
        *,
        verdict: Any = None,
    ) -> None:
        super().__init__(user_message, detail)
        self.verdict = verdict


class ApprovalMismatch(JarvisError):
    """An approval ticket is absent, expired, consumed, or mismatched."""


class BudgetExceeded(JarvisError):
    """The configured daily or monthly external-service budget is exhausted."""


class PromptTooLong(JarvisError):
    """The protected prompt content cannot fit the configured context budget."""


class LLMError(JarvisError):
    """Base class for model-provider failures."""


class LLMTimeout(LLMError):
    """The model provider did not respond before its deadline."""


class LLMUnavailable(LLMError):
    """The configured local model runtime is unavailable."""


class LLMRateLimited(LLMError):
    """The model provider rejected the request due to rate limits."""

    def __init__(
        self,
        user_message: str,
        detail: Mapping[str, Any] | None = None,
        *,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(user_message, detail)
        self.retry_after = retry_after


class LLMAuthError(LLMError):
    """The model provider rejected configured credentials."""


class LLMBadResponse(LLMError):
    """A provider response was malformed or violated its schema."""


class ToolError(JarvisError):
    """Base class for tool lookup, validation, and execution failures."""


class ToolNotFound(ToolError):
    """The requested tool is not registered."""


class ToolArgInvalid(ToolError):
    """Tool arguments failed schema or safety validation."""


class ToolTimeout(ToolError):
    """A managed tool exceeded its execution deadline."""


class ToolExecutionFailed(ToolError):
    """A tool process or in-process implementation failed."""


class MemoryError(JarvisError):
    """Base class for local memory-store failures."""


class MemoryCorrupted(MemoryError):
    """Stored memory failed an integrity check."""


class MemoryQuotaExceeded(MemoryError):
    """The configured local memory quota is exhausted."""


class RecoveryError(JarvisError):
    """Startup or checkpoint recovery could not complete safely."""


class ExitCode(IntEnum):
    SUCCESS = 0
    UNHANDLED_ERROR = 1
    CONFIG_OR_SECRETS = 2
    POLICY_DENIED = 3
    BUDGET_EXCEEDED = 4
    DATA_OR_RECOVERY = 5
    INTERRUPTED = 130


def exit_code_for(error: BaseException) -> ExitCode:
    """Map a handled exception to the documented process exit code."""
    if isinstance(error, KeyboardInterrupt | InterruptedError):
        return ExitCode.INTERRUPTED
    if isinstance(error, ConfigError | SecretsError):
        return ExitCode.CONFIG_OR_SECRETS
    if isinstance(error, PrivacyBlocked | PolicyDenied | ApprovalRequired | ApprovalMismatch):
        return ExitCode.POLICY_DENIED
    if isinstance(error, BudgetExceeded):
        return ExitCode.BUDGET_EXCEEDED
    if isinstance(error, MemoryCorrupted | RecoveryError):
        return ExitCode.DATA_OR_RECOVERY
    return ExitCode.UNHANDLED_ERROR

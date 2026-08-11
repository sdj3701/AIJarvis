"""Application exceptions with safe user-facing messages."""

from __future__ import annotations

from collections.abc import Mapping
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

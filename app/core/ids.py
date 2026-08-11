"""ULID-based identifiers with validated, filename-safe prefixes."""

from __future__ import annotations

import re
from typing import Protocol

from ulid import ULID

_PREFIX_PATTERN = re.compile(r"^[a-z][a-z0-9]{0,15}$")
_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


class IdGenerator(Protocol):
    def new(self) -> str: ...


class SystemUlidGenerator:
    def new(self) -> str:
        return str(ULID())


_generator: IdGenerator = SystemUlidGenerator()


def new_id(prefix: str, *, generator: IdGenerator | None = None) -> str:
    """Create ``<prefix>_<ULID>`` and reject unsafe or ambiguous components."""
    if not _PREFIX_PATTERN.fullmatch(prefix):
        raise ValueError("ID prefix must be lowercase ASCII alphanumeric without separators")
    ulid = (generator or _generator).new()
    if not _ULID_PATTERN.fullmatch(ulid):
        raise ValueError("ID generator returned an invalid ULID")
    return f"{prefix}_{ulid}"

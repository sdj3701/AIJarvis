"""Mask configured sensitive patterns and exact runtime secrets before logging."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import RLock
from typing import Literal, TypeAlias

from app.config.models import DetectorPolicy, MaskPolicy, PrivacyPolicy, SensitiveKind

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class Finding:
    """Metadata about a match; it deliberately never contains matched text."""

    detector_id: str
    action: Literal["mask", "block"]
    span: tuple[int, int]
    label: str
    kind: SensitiveKind


@dataclass(frozen=True, slots=True)
class _CompiledDetector:
    policy: DetectorPolicy
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class _Candidate:
    start: int
    end: int
    detector_id: str
    action: Literal["mask", "block"]
    label: str
    kind: SensitiveKind
    keep_tail: int


class LogMasker:
    """Thread-safe log masker built from privacy.yaml detectors."""

    def __init__(
        self,
        detectors: Sequence[DetectorPolicy],
        mask_policy: MaskPolicy,
    ) -> None:
        self._detectors = tuple(
            _CompiledDetector(policy=item, pattern=re.compile(item.pattern)) for item in detectors
        )
        self._replacement = mask_policy.replacement
        self._keep_tail = dict(mask_policy.keep_tail)
        self._secrets: set[str] = set()
        self._lock = RLock()

    @classmethod
    def from_policy(cls, policy: PrivacyPolicy) -> LogMasker:
        return cls(policy.detectors, policy.mask)

    def register_secret(self, secret: str) -> None:
        """Register an exact secret immediately after it is loaded."""
        if not secret or "\x00" in secret:
            raise ValueError("secret must be non-empty and contain no NUL")
        with self._lock:
            self._secrets.add(secret)

    def for_log(self, text: str) -> str:
        """Return masked log text; block detectors are masked on this output path."""
        return self.mask_text(text)[0]

    def mask_text(self, text: str) -> tuple[str, tuple[Finding, ...]]:
        with self._lock:
            secrets = tuple(self._secrets)

        candidates: list[_Candidate] = []
        for secret in secrets:
            start = 0
            while (found := text.find(secret, start)) >= 0:
                candidates.append(
                    _Candidate(
                        found,
                        found + len(secret),
                        "registered_secret",
                        "block",
                        "등록된 시크릿",
                        "secret",
                        0,
                    )
                )
                start = found + max(1, len(secret))

        for detector in self._detectors:
            for match in detector.pattern.finditer(text):
                if match.start() == match.end():
                    continue
                policy = detector.policy
                candidates.append(
                    _Candidate(
                        match.start(),
                        match.end(),
                        policy.id,
                        policy.action,
                        policy.label,
                        policy.kind,
                        self._keep_tail.get(policy.id, 0),
                    )
                )

        selected: list[_Candidate] = []
        cursor = 0
        for candidate in sorted(
            candidates, key=lambda item: (item.start, -(item.end - item.start))
        ):
            if candidate.start < cursor:
                continue
            selected.append(candidate)
            cursor = candidate.end

        parts: list[str] = []
        findings: list[Finding] = []
        cursor = 0
        for candidate in selected:
            parts.append(text[cursor : candidate.start])
            replacement = self._replacement.replace("{label}", candidate.label)
            if candidate.keep_tail:
                replacement += text[
                    max(candidate.start, candidate.end - candidate.keep_tail) : candidate.end
                ]
            parts.append(replacement)
            findings.append(
                Finding(
                    detector_id=candidate.detector_id,
                    action=candidate.action,
                    span=(candidate.start, candidate.end),
                    label=candidate.label,
                    kind=candidate.kind,
                )
            )
            cursor = candidate.end
        parts.append(text[cursor:])
        return "".join(parts), tuple(findings)

    def sanitize_value(self, value: object) -> tuple[JsonValue, tuple[Finding, ...]]:
        """Recursively mask every string key and value in JSON-compatible data."""
        findings: list[Finding] = []

        def sanitize(item: object) -> JsonValue:
            if isinstance(item, str):
                masked, item_findings = self.mask_text(item)
                findings.extend(item_findings)
                return masked
            if item is None or isinstance(item, bool | int | float):
                return item
            if isinstance(item, Mapping):
                result: dict[str, JsonValue] = {}
                for key, nested in item.items():
                    if not isinstance(key, str):
                        raise TypeError("event payload keys must be strings")
                    masked_key, key_findings = self.mask_text(key)
                    findings.extend(key_findings)
                    result[masked_key] = sanitize(nested)
                return result
            if isinstance(item, Sequence) and not isinstance(item, bytes | bytearray):
                return [sanitize(nested) for nested in item]
            raise TypeError(f"unsupported event payload type: {type(item).__name__}")

        return sanitize(value), tuple(findings)

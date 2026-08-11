"""Privacy gate for memory, API, logs, and TTS paths."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.config.models import PrivacyPolicy
from app.core.errors import PrivacyBlocked
from app.memory.models import MemoryRecord, SourceKind
from app.telemetry.masking import Finding, LogMasker

ExternalPurpose = Literal["llm", "search_query", "online_tts"]


class EventSink(Protocol):
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class ExternalTextDecision:
    text: str | None
    findings: tuple[Finding, ...]
    blocked: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PrivacyGate:
    """Apply independent transmission policies per output path."""

    masker: LogMasker | None = None
    privacy: PrivacyPolicy | None = None
    refuse_kinds: frozenset[str] = frozenset({"secret", "pii_high"})
    mark_sensitive_kinds: frozenset[str] = frozenset({"pii"})
    events: EventSink | None = None

    def for_log(self, text: str) -> str:
        if self.masker is None:
            return text
        return self.masker.for_log(text)

    def for_tts(self, text: str) -> str:
        if self.masker is None or self.privacy is None:
            return text
        masked, findings = self.masker.mask_text(text)
        tts_policy = self.privacy.outputs.tts
        if any(finding.kind in tts_policy.refuse_kinds for finding in findings):
            return tts_policy.fallback_text
        if len(masked) > tts_policy.max_chars:
            masked = masked[: tts_policy.max_chars]
        return masked

    def for_api(
        self,
        text: str,
        *,
        purpose: ExternalPurpose,
    ) -> ExternalTextDecision:
        if self.masker is None or self.privacy is None:
            return ExternalTextDecision(text=text, findings=(), blocked=False)

        api = self.privacy.api_transmission
        services = api.services
        if purpose == "llm" and not services.llm:
            return ExternalTextDecision(
                text=None,
                findings=(),
                blocked=True,
                reason="외부 llm 전송이 비활성화되어 있습니다.",
            )
        elif purpose == "search_query" and not services.search_query:
            return ExternalTextDecision(
                text=None,
                findings=(),
                blocked=True,
                reason="search_query 전송이 비활성화되어 있습니다.",
            )
        elif purpose == "online_tts" and not services.online_tts:
            return ExternalTextDecision(
                text=None,
                findings=(),
                blocked=True,
                reason="online_tts 전송이 비활성화되어 있습니다.",
            )

        masked, findings = self.masker.mask_text(text)
        blocked_findings = tuple(finding for finding in findings if finding.action == "block")
        secret_blocked = any(finding.kind in self.refuse_kinds for finding in blocked_findings)
        if secret_blocked:
            self._emit_block("api", blocked_findings, purpose=purpose)
            return ExternalTextDecision(
                text=None,
                findings=findings,
                blocked=True,
                reason="민감 정보가 포함되어 외부로 전송할 수 없습니다.",
            )
        if blocked_findings:
            self._emit_block("api", blocked_findings, purpose=purpose)
            action = api.on_block
            if action == "deny":
                return ExternalTextDecision(
                    text=None,
                    findings=findings,
                    blocked=True,
                    reason="프라이버시 정책으로 외부 전송이 차단되었습니다.",
                )
            if action == "local_only":
                return ExternalTextDecision(
                    text=None,
                    findings=findings,
                    blocked=True,
                    reason="로컬 전용 정책으로 외부 전송이 차단되었습니다.",
                )
            return ExternalTextDecision(
                text=None,
                findings=findings,
                blocked=True,
                reason="사용자 확인이 필요합니다.",
            )
        return ExternalTextDecision(text=masked, findings=findings, blocked=False)

    def for_external_text(
        self,
        text: str,
        *,
        purpose: Literal["search_query", "online_tts"],
    ) -> ExternalTextDecision:
        return self.for_api(text, purpose=purpose)

    def for_memory_write(
        self,
        rec: MemoryRecord,
        *,
        source_kind: SourceKind | None = None,
    ) -> tuple[MemoryRecord | None, tuple[Finding, ...]]:
        effective_source = source_kind or rec.source_kind
        if effective_source == "user_explicit":
            return rec, ()

        text = rec.value
        if self.masker is None:
            return rec, ()

        masked, findings = self.masker.mask_text(text)
        blocked = tuple(
            finding for finding in findings if finding.action == "block"
        )
        if blocked:
            secret_blocked = any(finding.kind in self.refuse_kinds for finding in blocked)
            if secret_blocked:
                if self.events is not None:
                    self.events.emit(
                        "privacy.block",
                        {
                            "path": "memory_write",
                            "detector_ids": sorted(
                                {finding.detector_id for finding in blocked}
                            ),
                            "source_kind": effective_source,
                        },
                    )
                return None, tuple(blocked)

        sensitivity: Literal["normal", "sensitive", "secret"] = rec.sensitivity
        if any(finding.kind in self.mark_sensitive_kinds for finding in findings):
            sensitivity = "sensitive"
        if any(finding.kind == "secret" for finding in findings):
            sensitivity = "secret"

        if masked == rec.value and sensitivity == rec.sensitivity:
            return rec, tuple(findings)

        updated = MemoryRecord(
            id=rec.id,
            schema_version=rec.schema_version,
            kind=rec.kind,
            key=rec.key,
            value=masked,
            status=rec.status,
            source_session_id=rec.source_session_id,
            source_turn_id=rec.source_turn_id,
            source_kind=rec.source_kind,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
            expires_at=rec.expires_at,
            sensitivity=sensitivity,
            supersedes=rec.supersedes,
            tags=rec.tags,
            deleted_at=rec.deleted_at,
            delete_reason=rec.delete_reason,
        )
        return updated, tuple(findings)

    def for_summarizer_text(self, text: str) -> str:
        if self.masker is None:
            return text
        return self.masker.mask_text(text)[0]

    def assert_api_allowed(self, text: str, *, purpose: ExternalPurpose) -> str:
        decision = self.for_api(text, purpose=purpose)
        if decision.text is None:
            raise PrivacyBlocked(
                decision.reason or "외부 전송이 차단되었습니다.",
                {"purpose": purpose},
            )
        return decision.text

    def _emit_block(
        self,
        path: str,
        findings: tuple[Finding, ...],
        *,
        purpose: ExternalPurpose,
    ) -> None:
        if self.events is None:
            return
        self.events.emit(
            "privacy.block",
            {
                "path": path,
                "purpose": purpose,
                "detector_ids": sorted({finding.detector_id for finding in findings}),
            },
        )

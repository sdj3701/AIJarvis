# 파이썬 공부 | scripts/app/privacy/gate.py
# 저장, 외부 전송, 로그, 음성 출력 전에 개인정보 처리 규칙을 적용합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Privacy gate for memory, API, logs, and TTS paths."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.config.models import PrivacyPolicy
from app.core.errors import PrivacyBlocked
from app.memory.models import MemoryRecord, SourceKind
from app.telemetry.masking import Finding, LogMasker

# 오른쪽 식을 계산한 값을 ExternalPurpose에 대입합니다.
ExternalPurpose = Literal["llm", "search_query", "online_tts"]


# EventSink: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class EventSink(Protocol):
    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


# ExternalTextDecision: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class ExternalTextDecision:
    # text: str | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    text: str | None
    # findings: tuple[Finding, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    findings: tuple[Finding, ...]
    # blocked: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    blocked: bool
    # reason을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    reason: str | None = None


# PrivacyGate: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class PrivacyGate:
    """Apply independent transmission policies per output path."""

    # masker을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    masker: LogMasker | None = None
    # privacy을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    privacy: PrivacyPolicy | None = None
    # frozenset()의 반환값을 refuse_kinds에 대입합니다.
    refuse_kinds: frozenset[str] = frozenset({"secret", "pii_high"})
    # frozenset()의 반환값을 mark_sensitive_kinds에 대입합니다.
    mark_sensitive_kinds: frozenset[str] = frozenset({"pii"})
    # events을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    events: EventSink | None = None

    # for_log(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text.
    # 반환 타입 힌트: 문자열(str).
    def for_log(self, text: str) -> str:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.masker is None.
        if self.masker is None:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return text
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.masker.for_log(text)

    # for_tts(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text.
    # 반환 타입 힌트: 문자열(str).
    def for_tts(self, text: str) -> str:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.masker is None or self.privacy is
        # None.
        if self.masker is None or self.privacy is None:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return text
        # 언패킹: 오른쪽 결과를 순서대로 (masked, findings)에 나누어 담습니다.
        masked, findings = self.masker.mask_text(text)
        # 오른쪽 식을 계산한 값을 tts_policy에 대입합니다.
        tts_policy = self.privacy.outputs.tts
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if any(finding.kind in tts_policy.refuse_kinds for finding in findings):
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return tts_policy.fallback_text
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(masked) > tts_policy.max_chars.
        if len(masked) > tts_policy.max_chars:
            # 오른쪽 식을 계산한 값을 masked에 대입합니다.
            # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
            masked = masked[: tts_policy.max_chars]
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return masked

    # for_api(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text, purpose.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: ExternalTextDecision.
    def for_api(
        self,
        text: str,
        *,
        purpose: ExternalPurpose,
    ) -> ExternalTextDecision:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.masker is None or self.privacy is
        # None.
        if self.masker is None or self.privacy is None:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return ExternalTextDecision(text=text, findings=(), blocked=False)

        # 오른쪽 식을 계산한 값을 api에 대입합니다.
        api = self.privacy.api_transmission
        # 오른쪽 식을 계산한 값을 services에 대입합니다.
        services = api.services
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: purpose == 'llm' and (not
        # services.llm).
        if purpose == "llm" and not services.llm:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return ExternalTextDecision(
                text=None,
                findings=(),
                blocked=True,
                reason="외부 llm 전송이 비활성화되어 있습니다.",
            )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: purpose == 'search_query' and (not
        # services.search_query).
        elif purpose == "search_query" and not services.search_query:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return ExternalTextDecision(
                text=None,
                findings=(),
                blocked=True,
                reason="search_query 전송이 비활성화되어 있습니다.",
            )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: purpose == 'online_tts' and (not
        # services.online_tts).
        elif purpose == "online_tts" and not services.online_tts:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return ExternalTextDecision(
                text=None,
                findings=(),
                blocked=True,
                reason="online_tts 전송이 비활성화되어 있습니다.",
            )

        # 언패킹: 오른쪽 결과를 순서대로 (masked, findings)에 나누어 담습니다.
        masked, findings = self.masker.mask_text(text)
        # tuple()의 반환값을 blocked_findings에 대입합니다.
        blocked_findings = tuple(finding for finding in findings if finding.action == "block")
        # any()의 반환값을 secret_blocked에 대입합니다.
        secret_blocked = any(finding.kind in self.refuse_kinds for finding in blocked_findings)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: secret_blocked.
        if secret_blocked:
            # self._emit_block()을 호출해 작업을 수행합니다.
            self._emit_block("api", blocked_findings, purpose=purpose)
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return ExternalTextDecision(
                text=None,
                findings=findings,
                blocked=True,
                reason="민감 정보가 포함되어 외부로 전송할 수 없습니다.",
            )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: blocked_findings.
        if blocked_findings:
            # self._emit_block()을 호출해 작업을 수행합니다.
            self._emit_block("api", blocked_findings, purpose=purpose)
            # 오른쪽 식을 계산한 값을 action에 대입합니다.
            action = api.on_block
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: action == 'deny'.
            if action == "deny":
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return ExternalTextDecision(
                    text=None,
                    findings=findings,
                    blocked=True,
                    reason="프라이버시 정책으로 외부 전송이 차단되었습니다.",
                )
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: action == 'local_only'.
            if action == "local_only":
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return ExternalTextDecision(
                    text=None,
                    findings=findings,
                    blocked=True,
                    reason="로컬 전용 정책으로 외부 전송이 차단되었습니다.",
                )
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return ExternalTextDecision(
                text=None,
                findings=findings,
                blocked=True,
                reason="사용자 확인이 필요합니다.",
            )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ExternalTextDecision(text=masked, findings=findings, blocked=False)

    # for_external_text(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text, purpose.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: ExternalTextDecision.
    def for_external_text(
        self,
        text: str,
        *,
        purpose: Literal["search_query", "online_tts"],
    ) -> ExternalTextDecision:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.for_api(text, purpose=purpose)

    # for_memory_write(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: rec, source_kind.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: tuple[MemoryRecord | None, tuple[Finding, ...]].
    def for_memory_write(
        self,
        rec: MemoryRecord,
        *,
        source_kind: SourceKind | None = None,
    ) -> tuple[MemoryRecord | None, tuple[Finding, ...]]:
        # 오른쪽 식을 계산한 값을 effective_source에 대입합니다.
        effective_source = source_kind or rec.source_kind
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: effective_source == 'user_explicit'.
        if effective_source == "user_explicit":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return rec, ()

        # 오른쪽 식을 계산한 값을 text에 대입합니다.
        text = rec.value
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.masker is None.
        if self.masker is None:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return rec, ()

        # 언패킹: 오른쪽 결과를 순서대로 (masked, findings)에 나누어 담습니다.
        masked, findings = self.masker.mask_text(text)
        # tuple()의 반환값을 blocked에 대입합니다.
        blocked = tuple(
            finding for finding in findings if finding.action == "block"
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: blocked.
        if blocked:
            # any()의 반환값을 secret_blocked에 대입합니다.
            secret_blocked = any(finding.kind in self.refuse_kinds for finding in blocked)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: secret_blocked.
            if secret_blocked:
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.events is not None.
                if self.events is not None:
                    # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
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
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return None, tuple(blocked)

        # 오른쪽 식을 계산한 값을 sensitivity에 대입합니다.
        sensitivity: Literal["normal", "sensitive", "secret"] = rec.sensitivity
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if any(finding.kind in self.mark_sensitive_kinds for finding in findings):
            # sensitivity에 문자열을 대입합니다.
            sensitivity = "sensitive"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: any((finding.kind == 'secret' for
        # finding in findings)).
        if any(finding.kind == "secret" for finding in findings):
            # sensitivity에 문자열을 대입합니다.
            sensitivity = "secret"

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: masked == rec.value and sensitivity ==
        # rec.sensitivity.
        if masked == rec.value and sensitivity == rec.sensitivity:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return rec, tuple(findings)

        # MemoryRecord()의 반환값을 updated에 대입합니다.
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
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return updated, tuple(findings)

    # for_summarizer_text(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text.
    # 반환 타입 힌트: 문자열(str).
    def for_summarizer_text(self, text: str) -> str:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.masker is None.
        if self.masker is None:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return text
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.masker.mask_text(text)[0]

    # assert_api_allowed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text, purpose.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 문자열(str).
    def assert_api_allowed(self, text: str, *, purpose: ExternalPurpose) -> str:
        # self.for_api()의 반환값을 decision에 대입합니다.
        decision = self.for_api(text, purpose=purpose)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: decision.text is None.
        if decision.text is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PrivacyBlocked(
                decision.reason or "외부 전송이 차단되었습니다.",
                {"purpose": purpose},
            )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return decision.text

    # _emit_block(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: path, findings, purpose.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _emit_block(
        self,
        path: str,
        findings: tuple[Finding, ...],
        *,
        purpose: ExternalPurpose,
    ) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.events is None.
        if self.events is None:
            # 이 함수를 여기서 끝냅니다. 값을 쓰지 않은 return은 None을 반환합니다.
            return
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        self.events.emit(
            "privacy.block",
            {
                "path": path,
                "purpose": purpose,
                "detector_ids": sorted({finding.detector_id for finding in findings}),
            },
        )

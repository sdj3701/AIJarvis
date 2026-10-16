# 파이썬 공부 | scripts/app/telemetry/masking.py
# 로그에 비밀 값과 민감한 패턴이 드러나지 않도록 가립니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Mask configured sensitive patterns and exact runtime secrets before logging."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import RLock
from typing import Literal, TypeAlias

from app.config.models import DetectorPolicy, MaskPolicy, PrivacyPolicy, SensitiveKind

# 오른쪽 식을 계산한 값을 JsonScalar에 대입합니다.
JsonScalar: TypeAlias = str | int | float | bool | None
# 오른쪽 식을 계산한 값을 JsonValue에 대입합니다.
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


# Finding: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class Finding:
    """Metadata about a match; it deliberately never contains matched text."""

    # detector_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    detector_id: str
    # action: Literal['mask', 'block'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    action: Literal["mask", "block"]
    # span: tuple[int, int] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    span: tuple[int, int]
    # label: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    label: str
    # kind: SensitiveKind 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    kind: SensitiveKind


# _CompiledDetector: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class _CompiledDetector:
    # policy: DetectorPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    policy: DetectorPolicy
    # pattern: re.Pattern[str] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    pattern: re.Pattern[str]


# _Candidate: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class _Candidate:
    # start: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    start: int
    # end: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    end: int
    # detector_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    detector_id: str
    # action: Literal['mask', 'block'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    action: Literal["mask", "block"]
    # label: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    label: str
    # kind: SensitiveKind 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    kind: SensitiveKind
    # keep_tail: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    keep_tail: int


# LogMasker: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class LogMasker:
    """Thread-safe log masker built from privacy.yaml detectors."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: detectors, mask_policy.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        detectors: Sequence[DetectorPolicy],
        mask_policy: MaskPolicy,
    ) -> None:
        # tuple()의 반환값을 self._detectors에 대입합니다.
        self._detectors = tuple(
            _CompiledDetector(policy=item, pattern=re.compile(item.pattern)) for item in detectors
        )
        # 오른쪽 식을 계산한 값을 self._replacement에 대입합니다.
        self._replacement = mask_policy.replacement
        # dict()의 반환값을 self._keep_tail에 대입합니다.
        self._keep_tail = dict(mask_policy.keep_tail)
        # set()의 반환값을 self._secrets에 대입합니다.
        self._secrets: set[str] = set()
        # RLock()의 반환값을 self._lock에 대입합니다.
        self._lock = RLock()

    # from_policy(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # cls는 이 메서드를 호출한 클래스입니다.
    # 입력: policy.
    # 반환 타입 힌트: LogMasker.
    # @classmethod: 객체 대신 클래스를 첫 인자로 받습니다.
    @classmethod
    def from_policy(cls, policy: PrivacyPolicy) -> LogMasker:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return cls(policy.detectors, policy.mask)

    # register_secret(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: secret.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def register_secret(self, secret: str) -> None:
        """Register an exact secret immediately after it is loaded."""
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not secret or '\x00' in secret.
        if not secret or "\x00" in secret:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("secret must be non-empty and contain no NUL")
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock:
            # add 메서드를 호출해 항목이나 기록을 추가합니다.
            self._secrets.add(secret)

    # for_log(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text.
    # 반환 타입 힌트: 문자열(str).
    def for_log(self, text: str) -> str:
        """Return masked log text; block detectors are masked on this output path."""
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.mask_text(text)[0]

    # mask_text(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text.
    # 반환 타입 힌트: tuple[str, tuple[Finding, ...]].
    def mask_text(self, text: str) -> tuple[str, tuple[Finding, ...]]:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock:
            # tuple()의 반환값을 secrets에 대입합니다.
            secrets = tuple(self._secrets)

        # candidates에 리스트(순서가 있고 수정 가능)을 대입합니다.
        candidates: list[_Candidate] = []
        # for 반복문: 대상의 항목을 하나씩 secret에 대입하며 아래 블록을 실행합니다.
        for secret in secrets:
            # start에 숫자 등 고정된 값을 대입합니다.
            start = 0
            # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
            while (found := text.find(secret, start)) >= 0:
                # 리스트 끝에 항목 하나를 추가합니다.
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
                # 오른쪽 식을 계산한 값을 start에 대입합니다.
                start = found + max(1, len(secret))

        # for 반복문: 대상의 항목을 하나씩 detector에 대입하며 아래 블록을 실행합니다.
        for detector in self._detectors:
            # for 반복문: 대상의 항목을 하나씩 match에 대입하며 아래 블록을 실행합니다.
            for match in detector.pattern.finditer(text):
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match.start() == match.end().
                if match.start() == match.end():
                    # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                    continue
                # 오른쪽 식을 계산한 값을 policy에 대입합니다.
                policy = detector.policy
                # 리스트 끝에 항목 하나를 추가합니다.
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

        # selected에 리스트(순서가 있고 수정 가능)을 대입합니다.
        selected: list[_Candidate] = []
        # cursor에 숫자 등 고정된 값을 대입합니다.
        cursor = 0
        # for 반복문: 대상의 항목을 하나씩 candidate에 대입하며 아래 블록을 실행합니다.
        for candidate in sorted(
            candidates, key=lambda item: (item.start, -(item.end - item.start))
        ):
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: candidate.start < cursor.
            if candidate.start < cursor:
                # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                continue
            # 리스트 끝에 항목 하나를 추가합니다.
            selected.append(candidate)
            # 오른쪽 식을 계산한 값을 cursor에 대입합니다.
            cursor = candidate.end

        # parts에 리스트(순서가 있고 수정 가능)을 대입합니다.
        parts: list[str] = []
        # findings에 리스트(순서가 있고 수정 가능)을 대입합니다.
        findings: list[Finding] = []
        # cursor에 숫자 등 고정된 값을 대입합니다.
        cursor = 0
        # for 반복문: 대상의 항목을 하나씩 candidate에 대입하며 아래 블록을 실행합니다.
        for candidate in selected:
            # 리스트 끝에 항목 하나를 추가합니다.
            parts.append(text[cursor : candidate.start])
            # self._replacement.replace()의 반환값을 replacement에 대입합니다.
            replacement = self._replacement.replace("{label}", candidate.label)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: candidate.keep_tail.
            if candidate.keep_tail:
                # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                replacement += text[
                    max(candidate.start, candidate.end - candidate.keep_tail) : candidate.end
                ]
            # 리스트 끝에 항목 하나를 추가합니다.
            parts.append(replacement)
            # 리스트 끝에 항목 하나를 추가합니다.
            findings.append(
                Finding(
                    detector_id=candidate.detector_id,
                    action=candidate.action,
                    span=(candidate.start, candidate.end),
                    label=candidate.label,
                    kind=candidate.kind,
                )
            )
            # 오른쪽 식을 계산한 값을 cursor에 대입합니다.
            cursor = candidate.end
        # 리스트 끝에 항목 하나를 추가합니다.
        parts.append(text[cursor:])
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return "".join(parts), tuple(findings)

    # sanitize_value(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: value.
    # 반환 타입 힌트: tuple[JsonValue, tuple[Finding, ...]].
    def sanitize_value(self, value: object) -> tuple[JsonValue, tuple[Finding, ...]]:
        """Recursively mask every string key and value in JSON-compatible data."""
        # findings에 리스트(순서가 있고 수정 가능)을 대입합니다.
        findings: list[Finding] = []

        # sanitize(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # 입력: item.
        # 반환 타입 힌트: JsonValue.
        def sanitize(item: object) -> JsonValue:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(item, str).
            if isinstance(item, str):
                # 언패킹: 오른쪽 결과를 순서대로 (masked, item_findings)에 나누어 담습니다.
                masked, item_findings = self.mask_text(item)
                # 반복 가능한 값의 항목들을 리스트 끝에 차례로 추가합니다.
                findings.extend(item_findings)
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return masked
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: item is None or isinstance(item,
            # bool | int | float).
            if item is None or isinstance(item, bool | int | float):
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return item
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(item, Mapping).
            if isinstance(item, Mapping):
                # result에 딕셔너리(키와 값의 쌍)을 대입합니다.
                result: dict[str, JsonValue] = {}
                # for 반복문: 대상의 항목을 하나씩 (key, nested)에 대입하며 아래 블록을
                # 실행합니다.
                for key, nested in item.items():
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(key, str).
                    if not isinstance(key, str):
                        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                        # 이동합니다.
                        raise TypeError("event payload keys must be strings")
                    # 언패킹: 오른쪽 결과를 순서대로 (masked_key, key_findings)에 나누어 담습니다.
                    masked_key, key_findings = self.mask_text(key)
                    # 반복 가능한 값의 항목들을 리스트 끝에 차례로 추가합니다.
                    findings.extend(key_findings)
                    # sanitize()의 반환값을 result[masked_key]에 대입합니다.
                    result[masked_key] = sanitize(nested)
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return result
            # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
            if isinstance(item, Sequence) and not isinstance(item, bytes | bytearray):
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
                return [sanitize(nested) for nested in item]
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError(f"unsupported event payload type: {type(item).__name__}")

        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return sanitize(value), tuple(findings)

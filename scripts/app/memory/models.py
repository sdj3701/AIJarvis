# 파이썬 공부 | scripts/app/memory/models.py
# 대화에서 보관할 기억 데이터의 구조를 정의합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Phase 2 memory record contracts aligned with DESIGN 5.2 and SCHEMAS 6-7."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from app.core.ids import new_id

# 오른쪽 식을 계산한 값을 RecordKind에 대입합니다.
RecordKind = Literal["fact", "correction", "summary", "doc_chunk"]
# 오른쪽 식을 계산한 값을 RecordStatus에 대입합니다.
RecordStatus = Literal["candidate", "confirmed", "superseded", "deleted"]
# 오른쪽 식을 계산한 값을 SourceKind에 대입합니다.
SourceKind = Literal["user_explicit", "summarizer", "import"]
# 오른쪽 식을 계산한 값을 Sensitivity에 대입합니다.
Sensitivity = Literal["normal", "sensitive", "secret"]
# 오른쪽 식을 계산한 값을 MatchKind에 대입합니다.
MatchKind = Literal["fts", "embedding", "key_exact"]

# KEY_PREFIXES에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
KEY_PREFIXES = (
    "identity.",
    "pref.",
    "env.",
    "project.",
    "contact.",
    "fact.",
)

# _ALLOWED_TRANSITIONS에 딕셔너리(키와 값의 쌍)을 대입합니다.
_ALLOWED_TRANSITIONS: dict[RecordStatus, frozenset[RecordStatus]] = {
    "candidate": frozenset({"confirmed", "deleted"}),
    "confirmed": frozenset({"superseded", "deleted"}),
    "superseded": frozenset(),
    "deleted": frozenset(),
}

# re.compile()의 반환값을 _KEY_PATTERN에 대입합니다.
_KEY_PATTERN = re.compile(
    r"^(identity|pref|env|project|contact|fact)\.[A-Za-z0-9_.-]+$"
)


# MemoryRecord: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class MemoryRecord:
    # id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    id: str
    # schema_version: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    schema_version: int
    # kind: RecordKind 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    kind: RecordKind
    # key: str | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    key: str | None
    # value: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    value: str
    # status: RecordStatus 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    status: RecordStatus
    # source_session_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    source_session_id: str
    # source_turn_id: str | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    source_turn_id: str | None
    # source_kind: SourceKind 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    source_kind: SourceKind
    # created_at: datetime 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    created_at: datetime
    # updated_at: datetime 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    updated_at: datetime
    # expires_at: datetime | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    expires_at: datetime | None
    # sensitivity: Sensitivity 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    sensitivity: Sensitivity
    # supersedes: str | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    supersedes: str | None
    # tags: tuple[str, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    tags: tuple[str, ...]
    # deleted_at을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    deleted_at: datetime | None = None
    # delete_reason을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    delete_reason: str | None = None

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.schema_version != 1.
        if self.schema_version != 1:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("memory schema_version must be 1")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.kind not in {'fact',
        # 'correction', 'summary',
        # 'doc_chunk'}.
        if self.kind not in {"fact", "correction", "summary", "doc_chunk"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("invalid memory kind")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if self.status not in {"candidate", "confirmed", "superseded", "deleted"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("invalid memory status")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.source_kind not in
        # {'user_explicit', 'summarizer',
        # 'import'}.
        if self.source_kind not in {"user_explicit", "summarizer", "import"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("invalid source_kind")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.sensitivity not in {'normal',
        # 'sensitive', 'secret'}.
        if self.sensitivity not in {"normal", "sensitive", "secret"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("invalid sensitivity")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(self.value, str) or not
        # self.value.strip().
        if not isinstance(self.value, str) or not self.value.strip():
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("memory value must be a non-empty string")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.kind in {'fact', 'correction'}
        # and (not self.key).
        if self.kind in {"fact", "correction"} and not self.key:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("fact/correction require a key")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.key is not None and (not
        # validate_memory_key(self.key)).
        if self.key is not None and not validate_memory_key(self.key):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("memory key namespace is invalid")
        # _require_aware()을 호출해 작업을 수행합니다.
        _require_aware(self.created_at, "created_at")
        # _require_aware()을 호출해 작업을 수행합니다.
        _require_aware(self.updated_at, "updated_at")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.expires_at is not None.
        if self.expires_at is not None:
            # _require_aware()을 호출해 작업을 수행합니다.
            _require_aware(self.expires_at, "expires_at")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.deleted_at is not None.
        if self.deleted_at is not None:
            # _require_aware()을 호출해 작업을 수행합니다.
            _require_aware(self.deleted_at, "deleted_at")


# MemoryQuery: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class MemoryQuery:
    # text: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    text: str
    # kinds에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    kinds: tuple[RecordKind, ...] = ("correction", "fact", "summary")
    # statuses에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    statuses: tuple[RecordStatus, ...] = ("confirmed",)
    # top_k에 숫자 등 고정된 값을 대입합니다.
    top_k: int = 8
    # include_candidates을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    include_candidates: bool = False
    # now을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    now: datetime | None = None


# ScoredRecord: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class ScoredRecord:
    # record: MemoryRecord 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    record: MemoryRecord
    # score: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    score: float
    # matched_on: MatchKind 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    matched_on: MatchKind


# MemorySearchResult: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class MemorySearchResult:
    # matches: tuple[ScoredRecord, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    matches: tuple[ScoredRecord, ...]
    # candidates에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    candidates: tuple[ScoredRecord, ...] = ()


# FactCandidate: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class FactCandidate:
    # id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    id: str
    # key: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    key: str
    # value: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    value: str
    # status: Literal['candidate'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    status: Literal["candidate"]
    # confidence: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    confidence: float
    # evidence_turn_ids: tuple[str, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    evidence_turn_ids: tuple[str, ...]

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self.evidence_turn_ids.
        if not self.evidence_turn_ids:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("evidence_turn_ids is required")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not validate_memory_key(self.key).
        if not validate_memory_key(self.key):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("fact candidate key is invalid")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not 0 <= self.confidence <= 1.
        if not 0 <= self.confidence <= 1:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("confidence must be between 0 and 1")


# SessionSummary: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class SessionSummary:
    # schema_version: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    schema_version: int
    # session_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    session_id: str
    # summary_record_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    summary_record_id: str
    # summary: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    summary: str
    # turn_count: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    turn_count: int
    # fact_candidates: tuple[FactCandidate, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    fact_candidates: tuple[FactCandidate, ...]
    # corrections: tuple[FactCandidate, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    corrections: tuple[FactCandidate, ...]
    # tags: tuple[str, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    tags: tuple[str, ...]
    # raw_path: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    raw_path: str
    # generated_by: dict[str, object] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    generated_by: dict[str, object]
    # cost_usd: Decimal 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    cost_usd: Decimal


# validate_memory_key(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: key.
# 반환 타입 힌트: 참/거짓(bool).
def validate_memory_key(key: str) -> bool:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return isinstance(key, str) and _KEY_PATTERN.fullmatch(key) is not None


# assert_transition_allowed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: current, target.
# 반환 타입 힌트: 별도 결과 없음(None).
def assert_transition_allowed(current: RecordStatus, target: RecordStatus) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: target not in
    # _ALLOWED_TRANSITIONS.get(current, frozenset()).
    if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        from app.core.errors import MemoryError as JarvisMemoryError

        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise JarvisMemoryError(
            "허용되지 않는 기억 상태 전이입니다.",
            {"from": current, "to": target},
        )


# new_fact_id(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: 문자열(str).
def new_fact_id() -> str:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return new_id("fact")


# new_summary_id(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: 문자열(str).
def new_summary_id() -> str:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return new_id("sum")


# _require_aware(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value, field.
# 반환 타입 힌트: 별도 결과 없음(None).
def _require_aware(value: datetime, field: str) -> None:
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError(f"{field} must be timezone-aware")

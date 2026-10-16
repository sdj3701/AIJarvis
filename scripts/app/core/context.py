# 파이썬 공부 | scripts/app/core/context.py
# 한 요청에서 함께 쓰는 객체와 작업 취소 상태를 관리합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Per-request dependencies and cooperative cancellation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from threading import Event
from typing import TYPE_CHECKING, Any, Literal, Protocol

from app.core.clock import Clock, RandomSource, Sleeper

# 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: TYPE_CHECKING.
if TYPE_CHECKING:
    from app.config.models import Settings

# _ULID_PATTERN에 문자열을 대입합니다.
_ULID_PATTERN = r"[0-9A-HJKMNP-TV-Z]{26}"


# EventWriter: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class EventWriter(Protocol):
    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


# AuditWriter: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class AuditWriter(Protocol):
    # write(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: record.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def write(self, record: Mapping[str, Any]) -> None: ...


# CancelToken: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class CancelToken(Protocol):
    # cancelled(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 참/거짓(bool).
    def cancelled(self) -> bool: ...

    # raise_if_cancelled(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def raise_if_cancelled(self) -> None: ...


# CancellationToken: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class CancellationToken:
    """Thread-safe cooperative cancellation token."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # Event()의 반환값을 self._event에 대입합니다.
        self._event = Event()

    # cancel(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def cancel(self) -> None:
        # self._event.set()을 호출해 작업을 수행합니다.
        self._event.set()

    # cancelled(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 참/거짓(bool).
    def cancelled(self) -> bool:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._event.is_set()

    # raise_if_cancelled(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def raise_if_cancelled(self) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.cancelled().
        if self.cancelled():
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise InterruptedError("작업이 취소되었습니다.")


# RequestContext: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class RequestContext:
    # request_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    request_id: str
    # session_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    session_id: str
    # turn_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    turn_id: str
    # task_id: str | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    task_id: str | None
    # started_at: datetime 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    started_at: datetime
    # clock: Clock 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    clock: Clock
    # sleeper: Sleeper 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    sleeper: Sleeper
    # random: RandomSource 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    random: RandomSource
    # settings: Settings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    settings: Settings  # injected; config is imported only under TYPE_CHECKING
    # events: EventWriter 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    events: EventWriter
    # audit: AuditWriter 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    audit: AuditWriter
    # cancel: CancelToken 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    cancel: CancelToken
    # interactive: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    interactive: bool
    # channel: Literal['text', 'voice'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    channel: Literal["text", "voice"]
    # memory_record_ids에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    memory_record_ids: tuple[str, ...] = ()

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("RequestContext.started_at must be timezone-aware")
        # _validate_id()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_id(self.request_id, "req")
        # _validate_id()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_id(self.session_id, "ses")
        # _validate_id()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_id(self.turn_id, "turn")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.task_id is not None.
        if self.task_id is not None:
            # _validate_id()으로 입력 형식과 허용 조건을 검사합니다.
            _validate_id(self.task_id, "task")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.channel not in {'text', 'voice'}.
        if self.channel not in {"text", "voice"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("RequestContext.channel must be text or voice")


# _validate_id(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value, prefix.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_id(value: str, prefix: str) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not
    # re.fullmatch(f'{prefix}_{_ULID_PATTERN}', value).
    if not re.fullmatch(rf"{prefix}_{_ULID_PATTERN}", value):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError(f"invalid {prefix} identifier")

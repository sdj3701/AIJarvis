# 파이썬 공부 | scripts/app/telemetry/events.py
# 개인정보를 처리한 이벤트를 날짜별 JSONL 로그에 저장합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Append privacy-safe structured events to daily JSONL files."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from app.core.clock import Clock
from app.core.errors import JarvisError
from app.telemetry.masking import JsonValue, LogMasker

# 오른쪽 식을 계산한 값을 Actor에 대입합니다.
Actor = Literal["user", "assistant", "system", "tool"]
# 오른쪽 식을 계산한 값을 Level에 대입합니다.
Level = Literal["debug", "info", "warn", "error"]

# frozenset()의 반환값을 EVENT_TYPES에 대입합니다.
EVENT_TYPES = frozenset(
    {
        "app.start",
        "app.stop",
        "command.memory",
        "turn.fast_path",
        "response.presentation",
        "app.permission.grant",
        "app.permission.revoke",
        "session.start",
        "session.checkpoint",
        "session.end",
        "session.summary_failed",
        "user.input",
        "llm.request",
        "llm.response",
        "llm.retry",
        "privacy.redact",
        "privacy.block",
        "memory.search",
        "memory.write",
        "memory.confirm",
        "memory.supersede",
        "memory.delete",
        "agent.step",
        "agent.stop",
        "tool.intent",
        "tool.result",
        "approval.request",
        "approval.grant",
        "approval.deny",
        "approval.mismatch",
        "approval.cancel",
        "policy.deny",
        "rag.index",
        "rag.semantic_unavailable",
        "rag.rerank",
        "rag.rerank_unavailable",
        "rag.grounding",
        "rag.query_plan",
        "rag.context",
        "secrets.dev_fallback",
        "retention.run",
        "backup.result",
        "backup.restore",
        "budget.warn",
        "budget.stop",
        "voice.recording",
        "voice.barge_in",
        "stt.result",
        "tts.result",
        "ui.state",
        "ui.hotkey",
        "recovery.start",
        "recovery.result",
        "error",
    }
)
# re.compile()의 반환값을 _ID_PATTERN에 대입합니다.
_ID_PATTERN = re.compile(r"^(req|ses|turn|task)_[0-9A-HJKMNP-TV-Z]{26}$")


# EventIdentity: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class EventIdentity:
    # request_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    request_id: str | None = None
    # session_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    session_id: str | None = None
    # turn_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    turn_id: str | None = None
    # task_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    task_id: str | None = None

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # for 반복문: 대상의 항목을 하나씩 value에 대입하며 아래 블록을 실행합니다.
        for value in (self.request_id, self.session_id, self.turn_id, self.task_id):
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: value is not None and
            # _ID_PATTERN.fullmatch(value) is
            # None.
            if value is not None and _ID_PATTERN.fullmatch(value) is None:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise ValueError("event identity contains an invalid identifier")


# JsonlEventWriter: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class JsonlEventWriter:
    """Synchronous event writer whose successful return means data was flushed."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: logs_dir, clock, masker, fsync_events.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        logs_dir: Path,
        *,
        clock: Clock,
        masker: LogMasker,
        fsync_events: bool,
    ) -> None:
        # Path()의 반환값을 self._logs_dir에 대입합니다.
        self._logs_dir = Path(logs_dir)
        # 오른쪽 식을 계산한 값을 self._clock에 대입합니다.
        self._clock = clock
        # 오른쪽 식을 계산한 값을 self._masker에 대입합니다.
        self._masker = masker
        # 오른쪽 식을 계산한 값을 self._fsync_events에 대입합니다.
        self._fsync_events = fsync_events
        # RLock()의 반환값을 self._lock에 대입합니다.
        self._lock = RLock()
        # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
        self._logs_dir.mkdir(parents=True, exist_ok=True)

    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload, identity, actor, level.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        identity: EventIdentity | None = None,
        actor: Actor = "system",
        level: Level = "info",
    ) -> None:
        """Mask the payload, then append one JSON line. Return means the line was flushed."""
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: event_type not in EVENT_TYPES.
        if event_type not in EVENT_TYPES:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError(f"unsupported event_type: {event_type}")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: actor not in {'user', 'assistant',
        # 'system', 'tool'}.
        if actor not in {"user", "assistant", "system", "tool"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("unsupported event actor")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: level not in {'debug', 'info', 'warn',
        # 'error'}.
        if level not in {"debug", "info", "warn", "error"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("unsupported event level")

        # 언패킹: 오른쪽 결과를 순서대로 (sanitized, findings)에 나누어 담습니다.
        sanitized, findings = self._masker.sanitize_value(payload)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(sanitized, dict).
        if not isinstance(sanitized, dict):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError("event payload must be a mapping")
        # Counter()의 반환값을 counts에 대입합니다.
        counts = Counter(finding.detector_id for finding in findings)
        # 오른쪽 식을 계산한 값을 redactions에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        redactions: list[JsonValue] = [
            {"detector_id": detector_id, "action": "mask", "count": count}
            for detector_id, count in sorted(counts.items())
        ]
        # self._clock.now()의 반환값을 now에 대입합니다.
        now = self._clock.now()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: now.tzinfo is None or now.utcoffset()
        # is None.
        if now.tzinfo is None or now.utcoffset() is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("event clock must return a timezone-aware datetime")
        # 오른쪽 식을 계산한 값을 event_identity에 대입합니다.
        event_identity = identity or EventIdentity()
        # envelope에 딕셔너리(키와 값의 쌍)을 대입합니다.
        envelope: dict[str, JsonValue] = {
            "v": 1,
            "ts": now.isoformat(timespec="milliseconds"),
            "event_type": event_type,
            "request_id": event_identity.request_id,
            "session_id": event_identity.session_id,
            "turn_id": event_identity.turn_id,
            "task_id": event_identity.task_id,
            "actor": actor,
            "level": level,
            "payload": sanitized,
            "redactions": redactions,
        }
        # json.dumps()의 반환값을 line에 대입합니다.
        line = json.dumps(
            envelope,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        # 오른쪽 식을 계산한 값을 path에 대입합니다.
        path = self._logs_dir / f"events-{now.date().isoformat()}.jsonl"

        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with self._lock, path.open("a", encoding="utf-8", newline="\n") as output:
                # 열린 출력 대상에 데이터를 기록합니다.
                output.write(line)
                # 열린 출력 대상에 데이터를 기록합니다.
                output.write("\n")
                # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
                output.flush()
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._fsync_events.
                if self._fsync_events:
                    # 운영체제에 파일 내용을 저장 장치로 동기화하도록 요청합니다.
                    os.fsync(output.fileno())
        # OSError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except OSError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise JarvisError(
                "이벤트 로그를 기록할 수 없습니다.",
                {"error_type": type(error).__name__, "log_file": path.name},
            ) from error

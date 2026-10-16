# 파이썬 공부 | scripts/app/core/recovery.py
# 비정상 종료 후 남은 임시 파일과 불완전한 로그를 정리합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Startup filesystem recovery: leftover ``*.tmp`` files and broken JSONL tails."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.core.atomic import write_atomic
from app.core.errors import RecoveryError


# EventSink: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class EventSink(Protocol):
    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


# RecoveryAction: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class RecoveryAction:
    # action: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    action: str
    # source: Path | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    source: Path | None
    # quarantined: Path | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    quarantined: Path | None
    # restored_turns: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    restored_turns: int


# RecoveryReport: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class RecoveryReport:
    # tmp_files: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    tmp_files: int
    # broken_tails: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    broken_tails: int
    # actions: tuple[RecoveryAction, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    actions: tuple[RecoveryAction, ...]


# _unique_target(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: directory, name.
# 반환 타입 힌트: Path.
def _unique_target(directory: Path, name: str) -> Path:
    # 오른쪽 식을 계산한 값을 candidate에 대입합니다.
    candidate = directory / name
    # sequence에 숫자 등 고정된 값을 대입합니다.
    sequence = 1
    # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
    while candidate.exists():
        # 오른쪽 식을 계산한 값을 candidate에 대입합니다.
        candidate = directory / f"{name}.{sequence}"
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        sequence += 1
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return candidate


# _quarantine_tmp(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: data_root, source, quarantine.
# 반환 타입 힌트: Path.
def _quarantine_tmp(data_root: Path, source: Path, quarantine: Path) -> Path:
    # source.relative_to()의 반환값을 relative에 대입합니다.
    relative = source.relative_to(data_root)
    # _unique_target()의 반환값을 target에 대입합니다.
    target = _unique_target(quarantine, "__".join(relative.parts))
    # os.replace()을 호출해 작업을 수행합니다.
    os.replace(source, target)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return target


# _parse_json_line(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: line.
# 반환 타입 힌트: dict[str, Any].
def _parse_json_line(line: bytes) -> dict[str, Any]:
    # line.decode()의 반환값을 decoded에 대입합니다.
    decoded = line.decode("utf-8")
    # json.loads()의 반환값을 parsed에 대입합니다.
    parsed = json.loads(decoded)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(parsed, dict).
    if not isinstance(parsed, dict):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("JSONL record must be an object")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return parsed


# recover_jsonl_tail(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, quarantine.
# 반환 타입 힌트: RecoveryAction | None.
def recover_jsonl_tail(path: Path, quarantine: Path) -> RecoveryAction | None:
    """Move only a malformed final JSONL line aside and keep all valid lines."""
    # path.read_bytes()의 반환값을 raw에 대입합니다.
    raw = path.read_bytes()
    # raw.splitlines()의 반환값을 lines에 대입합니다.
    lines = raw.splitlines(keepends=True)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not lines.
    if not lines:
        # None을 반환하고 이 함수의 실행을 끝냅니다.
        return None

    # for 반복문: 대상의 항목을 하나씩 (index, line)에 대입하며 아래 블록을 실행합니다.
    for index, line in enumerate(lines):
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # _parse_json_line()을 호출해 작업을 수행합니다.
            _parse_json_line(line)
        # (UnicodeError, json.JSONDecodeError, ValueError)를 잡아 처리합니다. as 뒤의 이름에는
        # 발생한 예외 객체가 담깁니다.
        except (UnicodeError, json.JSONDecodeError, ValueError) as error:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: index != len(lines) - 1.
            if index != len(lines) - 1:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise RecoveryError(
                    "JSONL 중간 레코드가 손상되었습니다.",
                    {"file": path.name, "line": index + 1},
                ) from error
            # _unique_target()의 반환값을 tail_target에 대입합니다.
            tail_target = _unique_target(quarantine, f"{path.stem}.tail")
            # write_atomic()을 호출해 작업을 수행합니다.
            write_atomic(tail_target, line)
            # write_atomic()을 호출해 작업을 수행합니다.
            write_atomic(path, b"".join(lines[:index]))
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return RecoveryAction("quarantine_broken_tail", path, tail_target, restored_turns=index)
    # None을 반환하고 이 함수의 실행을 끝냅니다.
    return None


# recover_startup(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: data_root, events.
# 반환 타입 힌트: RecoveryReport.
def recover_startup(data_root: Path, events: EventSink) -> RecoveryReport:
    """Quarantine leftover temp files and broken JSONL tails before serving traffic."""
    # Path(data_root).resolve()의 반환값을 root에 대입합니다.
    root = Path(data_root).resolve(strict=False)
    # 오른쪽 식을 계산한 값을 quarantine에 대입합니다.
    quarantine = root / "state" / "quarantine"
    # 오른쪽 식을 계산한 값을 raw_dir에 대입합니다.
    raw_dir = root / "memory" / "raw"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    quarantine.mkdir(parents=True, exist_ok=True)
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # sorted()의 반환값을 temporary_files에 대입합니다.
        temporary_files = sorted(
            path
            for path in root.rglob("*.tmp")
            if path.is_file() and not path.is_relative_to(quarantine)
        )
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        events.emit(
            "recovery.start",
            {"unfinished_sessions": 0, "tmp_files": len(temporary_files), "running_steps": 0},
        )

        # actions에 리스트(순서가 있고 수정 가능)을 대입합니다.
        actions: list[RecoveryAction] = []
        # for 반복문: 대상의 항목을 하나씩 temporary에 대입하며 아래 블록을 실행합니다.
        for temporary in temporary_files:
            # _quarantine_tmp()의 반환값을 target에 대입합니다.
            target = _quarantine_tmp(root, temporary, quarantine)
            # RecoveryAction()의 반환값을 action에 대입합니다.
            action = RecoveryAction("quarantine_tmp", temporary, target, restored_turns=0)
            # 리스트 끝에 항목 하나를 추가합니다.
            actions.append(action)
            # _emit_result()을 호출해 작업을 수행합니다.
            _emit_result(events, action)

        # for 반복문: 대상의 항목을 하나씩 raw_path에 대입하며 아래 블록을 실행합니다.
        for raw_path in sorted(raw_dir.glob("*.jsonl")):
            # recover_jsonl_tail()의 반환값을 tail_action에 대입합니다.
            tail_action = recover_jsonl_tail(raw_path, quarantine)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tail_action is not None.
            if tail_action is not None:
                # 리스트 끝에 항목 하나를 추가합니다.
                actions.append(tail_action)
                # _emit_result()을 호출해 작업을 수행합니다.
                _emit_result(events, tail_action)

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not actions.
        if not actions:
            # RecoveryAction()의 반환값을 empty_action에 대입합니다.
            empty_action = RecoveryAction("none", None, None, restored_turns=0)
            # 리스트 끝에 항목 하나를 추가합니다.
            actions.append(empty_action)
            # _emit_result()을 호출해 작업을 수행합니다.
            _emit_result(events, empty_action)
    # RecoveryError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except RecoveryError:
        # _emit_failure()을 호출해 작업을 수행합니다.
        _emit_failure(events)
        # 현재 예외를 다시 발생시켜 호출한 쪽으로 전달합니다.
        raise
    # OSError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except OSError as error:
        # _emit_failure()을 호출해 작업을 수행합니다.
        _emit_failure(events)
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise RecoveryError(
            "시작 복구 중 파일을 안전하게 처리하지 못했습니다.",
            {"error_type": type(error).__name__},
        ) from error

    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return RecoveryReport(
        tmp_files=sum(action.action == "quarantine_tmp" for action in actions),
        broken_tails=sum(action.action == "quarantine_broken_tail" for action in actions),
        actions=tuple(actions),
    )


# _emit_result(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: events, action.
# 반환 타입 힌트: 별도 결과 없음(None).
def _emit_result(events: EventSink, action: RecoveryAction) -> None:
    # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
    events.emit(
        "recovery.result",
        {
            "action": action.action,
            "session_id": action.source.stem
            if action.source and action.source.suffix == ".jsonl"
            else None,
            "quarantined": str(action.quarantined) if action.quarantined else None,
            "restored_turns": action.restored_turns,
        },
    )


# _emit_failure(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: events.
# 반환 타입 힌트: 별도 결과 없음(None).
def _emit_failure(events: EventSink) -> None:
    # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
    events.emit(
        "recovery.result",
        {
            "action": "failed",
            "session_id": None,
            "quarantined": None,
            "restored_turns": 0,
        },
    )

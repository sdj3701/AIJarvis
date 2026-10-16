# 파이썬 공부 | scripts/app/telemetry/audit.py
# 감사 기록을 이어 쓰고 해시 연결로 기록 변조를 확인할 수 있게 합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Append-only audit log writer with hash chain integrity."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.canonical import canonical_json
from app.core.clock import Clock

# 오른쪽 식을 계산한 값을 _ZERO_HASH에 대입합니다.
_ZERO_HASH = "0" * 64
# _AUDIT_VERSION에 숫자 등 고정된 값을 대입합니다.
_AUDIT_VERSION = 1


# JsonlAuditWriter: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class JsonlAuditWriter:
    """Write tool audit records under data_root/logs with monotonic seq and hash chain."""

    # logs_dir: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    logs_dir: Path
    # database_path: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    database_path: Path
    # clock: Clock 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    clock: Clock
    # fsync을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    fsync: bool = True
    # field()의 반환값을 _lock에 대입합니다.
    _lock: threading.Lock = field(default_factory=threading.Lock)
    # 오른쪽 식을 계산한 값을 _prev_hash에 대입합니다.
    _prev_hash: str = _ZERO_HASH
    # _db_ready을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    _db_ready: bool = False

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    # write(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: record.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def write(self, record: Mapping[str, Any]) -> None:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock:
            # self._ensure_db()을 호출해 작업을 수행합니다.
            self._ensure_db()
            # _next_audit_seq()의 반환값을 seq에 대입합니다.
            seq = _next_audit_seq(self.database_path)
            # self.clock.now().isoformat()의 반환값을 ts에 대입합니다.
            ts = self.clock.now().isoformat(timespec="milliseconds")
            # dict()의 반환값을 body에 대입합니다.
            body = dict(record)
            # body.setdefault()을 호출해 작업을 수행합니다.
            body.setdefault("v", _AUDIT_VERSION)
            # 오른쪽 식을 계산한 값을 body['seq']에 대입합니다.
            body["seq"] = seq
            # 오른쪽 식을 계산한 값을 body['ts']에 대입합니다.
            body["ts"] = ts
            # 오른쪽 식을 계산한 값을 body['prev_hash']에 대입합니다.
            body["prev_hash"] = self._prev_hash
            # 오른쪽 식을 계산한 값을 hash_body에 대입합니다.
            # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
            hash_body = {
                key: value for key, value in body.items() if key not in {"prev_hash", "entry_hash"}
            }
            # _entry_hash()의 반환값을 entry_hash에 대입합니다.
            entry_hash = _entry_hash(self._prev_hash, hash_body)
            # 오른쪽 식을 계산한 값을 body['entry_hash']에 대입합니다.
            body["entry_hash"] = entry_hash
            # 오른쪽 식을 계산한 값을 line에 대입합니다.
            line = json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n"
            # self._audit_path()의 반환값을 path에 대입합니다.
            path = self._audit_path(ts)
            # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
            path.parent.mkdir(parents=True, exist_ok=True)
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with path.open("a", encoding="utf-8") as stream:
                # 열린 출력 대상에 데이터를 기록합니다.
                stream.write(line)
                # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
                stream.flush()
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.fsync.
                if self.fsync:
                    import os

                    # 운영체제에 파일 내용을 저장 장치로 동기화하도록 요청합니다.
                    os.fsync(stream.fileno())
            # 오른쪽 식을 계산한 값을 self._prev_hash에 대입합니다.
            self._prev_hash = entry_hash
            # _store_prev_hash()을 호출해 작업을 수행합니다.
            _store_prev_hash(self.database_path, entry_hash)

    # _ensure_db(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _ensure_db(self) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._db_ready.
        if self._db_ready:
            # 이 함수를 여기서 끝냅니다. 값을 쓰지 않은 return은 None을 반환합니다.
            return
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # _load_prev_hash()의 반환값을 self._prev_hash에 대입합니다.
            self._prev_hash = _load_prev_hash(self.database_path)
        # sqlite3.OperationalError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
        # 담깁니다.
        except sqlite3.OperationalError:
            # 오른쪽 식을 계산한 값을 self._prev_hash에 대입합니다.
            self._prev_hash = _ZERO_HASH
        # self._db_ready을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        self._db_ready = True

    # _audit_path(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: ts_text.
    # 반환 타입 힌트: Path.
    def _audit_path(self, ts_text: str) -> Path:
        # 오른쪽 식을 계산한 값을 day에 대입합니다.
        # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
        day = ts_text[:10]
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.logs_dir / f"audit-{day}.jsonl"


# verify_audit_chain(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: logs_dir.
# 반환 타입 힌트: tuple[bool, str | None].
def verify_audit_chain(logs_dir: Path) -> tuple[bool, str | None]:
    """Return (ok, error_message). Walk all audit files in date order."""
    # sorted()의 반환값을 files에 대입합니다.
    files = sorted(logs_dir.glob("audit-*.jsonl"))
    # 오른쪽 식을 계산한 값을 prev_hash에 대입합니다.
    prev_hash = _ZERO_HASH
    # last_seq에 숫자 등 고정된 값을 대입합니다.
    last_seq = 0
    # for 반복문: 대상의 항목을 하나씩 path에 대입하며 아래 블록을 실행합니다.
    for path in files:
        # for 반복문: 대상의 항목을 하나씩 (line_no, line)에 대입하며 아래 블록을 실행합니다.
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not line.strip().
            if not line.strip():
                # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                continue
            # json.loads()의 반환값을 record에 대입합니다.
            record = json.loads(line)
            # record.get()의 반환값을 expected_prev에 대입합니다.
            expected_prev = record.get("prev_hash")
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: expected_prev != prev_hash.
            if expected_prev != prev_hash:
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return False, f"{path.name}:{line_no} prev_hash mismatch"
            # int()의 반환값을 seq에 대입합니다.
            seq = int(record["seq"])
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: seq <= last_seq.
            if seq <= last_seq:
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return False, f"{path.name}:{line_no} seq not monotonic ({seq} <= {last_seq})"
            # 오른쪽 식을 계산한 값을 last_seq에 대입합니다.
            last_seq = seq
            # record.pop()의 반환값을 entry_hash에 대입합니다.
            entry_hash = record.pop("entry_hash")
            # record.pop()의 반환값을 stored_prev에 대입합니다.
            stored_prev = record.pop("prev_hash")
            # _entry_hash()의 반환값을 computed에 대입합니다.
            computed = _entry_hash(stored_prev, record)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: computed != entry_hash.
            if computed != entry_hash:
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return False, f"{path.name}:{line_no} entry_hash mismatch"
            # 오른쪽 식을 계산한 값을 prev_hash에 대입합니다.
            prev_hash = entry_hash
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return True, None


# read_audit_records(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: logs_dir.
# 반환 타입 힌트: list[dict[str, Any]].
def read_audit_records(logs_dir: Path) -> list[dict[str, Any]]:
    # records에 리스트(순서가 있고 수정 가능)을 대입합니다.
    records: list[dict[str, Any]] = []
    # for 반복문: 대상의 항목을 하나씩 path에 대입하며 아래 블록을 실행합니다.
    for path in sorted(logs_dir.glob("audit-*.jsonl")):
        # for 반복문: 대상의 항목을 하나씩 line에 대입하며 아래 블록을 실행합니다.
        for line in path.read_text(encoding="utf-8").splitlines():
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: line.strip().
            if line.strip():
                # 리스트 끝에 항목 하나를 추가합니다.
                records.append(json.loads(line))
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return records


# _entry_hash(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: prev_hash, record_without_hashes.
# 반환 타입 힌트: 문자열(str).
def _entry_hash(prev_hash: str, record_without_hashes: Mapping[str, Any]) -> str:
    # 오른쪽 식을 계산한 값을 payload에 대입합니다.
    payload = prev_hash.encode("utf-8") + canonical_json(dict(record_without_hashes))
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return hashlib.sha256(payload).hexdigest()


# _next_audit_seq(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: database_path.
# 반환 타입 힌트: 정수(int).
def _next_audit_seq(database_path: Path) -> int:
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with sqlite3.connect(database_path) as connection:
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute("BEGIN IMMEDIATE")
        # 아래 함수()의 반환값을 row에 대입합니다.
        row = connection.execute(
            "SELECT value FROM meta WHERE key='audit_seq'"
        ).fetchone()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: row is None.
        if row is None:
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            connection.execute("ROLLBACK")
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise sqlite3.OperationalError("meta.audit_seq is not initialized")
        # 오른쪽 식을 계산한 값을 current에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        current = int(row[0]) if row is not None else 0
        # 오른쪽 식을 계산한 값을 new_value에 대입합니다.
        new_value = current + 1
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute(
            "UPDATE meta SET value=? WHERE key='audit_seq'",
            (str(new_value),),
        )
        # 데이터베이스 변경 내용을 확정합니다.
        connection.commit()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return new_value


# _load_prev_hash(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: database_path.
# 반환 타입 힌트: 문자열(str).
def _load_prev_hash(database_path: Path) -> str:
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with sqlite3.connect(database_path) as connection:
        # 아래 함수()의 반환값을 row에 대입합니다.
        row = connection.execute(
            "SELECT value FROM meta WHERE key='audit_prev_hash'"
        ).fetchone()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: row is None.
        if row is None:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return _ZERO_HASH
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return str(row[0])


# _store_prev_hash(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: database_path, value.
# 반환 타입 힌트: 별도 결과 없음(None).
def _store_prev_hash(database_path: Path, value: str) -> None:
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with sqlite3.connect(database_path) as connection:
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('audit_prev_hash', ?)",
            (value,),
        )
        # 데이터베이스 변경 내용을 확정합니다.
        connection.commit()

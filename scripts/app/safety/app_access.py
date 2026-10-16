# 파이썬 공부 | scripts/app/safety/app_access.py
# 사용자가 허용한 앱 접근 권한을 저장하고 조회합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Persistent per-user app permissions, distinct from disposable discovery cache."""

from __future__ import annotations

import csv
import ctypes
import hashlib
import json
import os
import sqlite3
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.errors import PolicyDenied
from app.safety.app_catalog import discover_apps

# _BLOCKED에 집합(중복 없는 항목)을 대입합니다.
_BLOCKED = {
    "cmd",
    "powershell",
    "pwsh",
    "wscript",
    "cscript",
    "mshta",
    "rundll32",
    "regsvr32",
    "regedit",
    "mmc",
    "control",
    "msiexec",
    "python",
    "pythonw",
}


# user_sid(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: 문자열(str).
# @로 시작하는 데코레이터는 아래 함수에 추가 동작이나 메타데이터를 적용합니다.
@lru_cache(maxsize=1)
def user_sid() -> str:
    # 오른쪽 식을 계산한 값을 exe에 대입합니다.
    exe = Path(os.environ["SYSTEMROOT"]) / "System32/whoami.exe"
    # subprocess.run()의 반환값을 result에 대입합니다.
    result = subprocess.run(
        [str(exe), "/user", "/fo", "csv", "/nh"],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    # 오른쪽 식을 계산한 값을 sid에 대입합니다.
    sid = next(csv.reader([result.stdout.strip()]))[-1]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not sid.startswith('S-1-').
    if not sid.startswith("S-1-"):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied("사용자 SID를 확인할 수 없습니다.")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return sid


# locked_identity(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: Iterator[dict[str, Any]].
# @contextmanager: yield 앞은 with 진입 준비, 뒤는 with 종료 시 처리입니다.
@contextmanager
def locked_identity(path: Path) -> Iterator[dict[str, Any]]:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not path.is_absolute().
    if not path.is_absolute():
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied("앱 실행 대상은 절대 경로여야 합니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: str(path).startswith('\\\\').
    if str(path).startswith("\\\\"):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied("네트워크 및 장치 경로의 앱은 지원하지 않습니다.")
    # path.resolve()의 반환값을 path에 대입합니다.
    path = path.resolve(strict=True)
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if (
        path.suffix.lower() != ".exe"
        or path.stem.lower() in _BLOCKED
        or any(word in path.stem.lower() for word in ("unins", "uninstall", "setup", "installer"))
    ):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied("이 실행 대상은 앱 자동 실행에서 지원하지 않습니다.")
    # ctypes.WinDLL()의 반환값을 kernel에 대입합니다.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    # kernel.CreateFileW.argtypes에 리스트(순서가 있고 수정 가능)을 대입합니다.
    kernel.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    # 오른쪽 식을 계산한 값을 kernel.CreateFileW.restype에 대입합니다.
    kernel.CreateFileW.restype = ctypes.c_void_p
    # kernel.CloseHandle.argtypes에 리스트(순서가 있고 수정 가능)을 대입합니다.
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    # kernel.CreateFileW()의 반환값을 handle에 대입합니다.
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0, None)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: handle == ctypes.c_void_p(-1).value.
    if handle == ctypes.c_void_p(-1).value:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied("앱 파일을 잠글 수 없습니다. 변경 작업이 끝난 뒤 다시 요청하세요.")
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with path.open("rb") as stream:
            # 아래 함수()의 반환값을 digest에 대입합니다.
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        # path.stat()의 반환값을 stat에 대입합니다.
        stat = path.stat()
        # yield는 값을 건네고 실행을 잠시 멈춥니다. 다음 요청이 오면 이어서 진행합니다.
        yield {
            "exe_path": str(path),
            "sha256": digest,
            "sid": user_sid(),
            "file_identity": [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns],
        }
    # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
    finally:
        # kernel.CloseHandle()을 호출해 작업을 수행합니다.
        kernel.CloseHandle(handle)


# AppAccess: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class AppAccess:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: root, dynamic, ttl, limit, saved_permissions.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self, root: Path, *, dynamic: bool = False, ttl: float = 300, limit: int = 2000,
        saved_permissions: bool = True,
    ) -> None:
        # 오른쪽 식을 계산한 값을 self.path에 대입합니다.
        self.path = root / "state" / "app_permissions" / "approvals.sqlite3"
        # 언패킹: 오른쪽 결과를 순서대로 (self.dynamic, self.ttl, self.limit)에 나누어 담습니다.
        self.dynamic, self.ttl, self.limit = dynamic, ttl, limit
        # 오른쪽 식을 계산한 값을 self.saved_permissions에 대입합니다.
        self.saved_permissions = saved_permissions
        # self._secured을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self._secured = False
        # threading.RLock()의 반환값을 self.lock에 대입합니다.
        self.lock = threading.RLock()
        # self._catalog에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self._catalog: list[tuple[str, Path]] = []
        # self._catalog_metadata에 딕셔너리(키와 값의 쌍)을 대입합니다.
        self._catalog_metadata: dict[str, dict[str, Any]] = {}
        # self._expires에 숫자 등 고정된 값을 대입합니다.
        self._expires = 0.0
        # self._choices에 딕셔너리(키와 값의 쌍)을 대입합니다.
        self._choices: dict[str, tuple[float, str, list[dict[str, Any]]]] = {}
        # set()의 반환값을 self._finished에 대입합니다.
        self._finished: set[str] = set()

    # connection(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Iterator[sqlite3.Connection].
    # @contextmanager: yield 앞은 with 진입 준비, 뒤는 with 종료 시 처리입니다.
    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # 오른쪽 식을 계산한 값을 new에 대입합니다.
            new = not self.path.exists()
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: new or not self._secured.
            if new or not self._secured:
                # 오른쪽 식을 계산한 값을 acl에 대입합니다.
                acl = Path(os.environ["SYSTEMROOT"]) / "System32/icacls.exe"
                # subprocess.run()을 호출해 작업을 수행합니다.
                subprocess.run(
                    [str(acl), str(self.path.parent), "/inheritance:r", "/grant:r",
                     f"*{user_sid()}:(OI)(CI)(F)"],
                    capture_output=True, check=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: new or not self._secured.
                if new or not self._secured:
                    # 오른쪽 식을 계산한 값을 acl에 대입합니다.
                    acl = Path(os.environ["SYSTEMROOT"]) / "System32/icacls.exe"
                    # subprocess.run()을 호출해 작업을 수행합니다.
                    subprocess.run(
                        [
                            str(acl),
                            str(self.path),
                            "/inheritance:r",
                            "/grant:r",
                            f"*{user_sid()}:(F)",
                        ],
                        capture_output=True,
                        check=True,
                        timeout=5,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    # self._secured을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
                    self._secured = True
                # 오른쪽 식을 계산한 값을 version에 대입합니다.
                version = db.execute("PRAGMA user_version").fetchone()[0]
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: version not in (0, 1, 2).
                if version not in (0, 1, 2):
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise PolicyDenied("앱 승인 저장소 버전을 지원하지 않습니다.")
                # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
                db.execute(
                    "CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, "
                    "sid TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, "
                    "name TEXT NOT NULL, granted_at TEXT NOT NULL, channel TEXT NOT NULL, "
                    "UNIQUE(sid,path,sha256))"
                )
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: version < 2.
                if version < 2:
                    # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할
                    # 값입니다.
                    db.execute("ALTER TABLE approvals ADD COLUMN file_identity TEXT")
                # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
                db.execute("PRAGMA user_version=2")
                # yield는 값을 건네고 실행을 잠시 멈춥니다. 다음 요청이 오면 이어서 진행합니다.
                yield db
        # (sqlite3.Error, OSError, subprocess.SubprocessError)를 잡아 처리합니다. as 뒤의 이름에는
        # 발생한 예외 객체가
        # 담깁니다.
        except (sqlite3.Error, OSError, subprocess.SubprocessError) as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("앱 승인 저장소를 읽거나 저장할 수 없습니다.") from error

    # allowed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: identity.
    # 반환 타입 힌트: 참/거짓(bool).
    def allowed(self, identity: dict[str, Any]) -> bool:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self.saved_permissions.
        if not self.saved_permissions:
            # False을 반환하고 이 함수의 실행을 끝냅니다.
            return False
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self.connection() as db:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return (
                db.execute(
                    "SELECT 1 FROM approvals WHERE sid=? AND path=? AND sha256=?",
                    (identity["sid"], identity["exe_path"].casefold(), identity["sha256"]),
                ).fetchone()
                is not None
            )

    # grant(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: identity, name, channel.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def grant(self, identity: dict[str, Any], name: str, channel: str) -> None:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self.connection() as db:
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            db.execute(
                "INSERT OR IGNORE INTO approvals VALUES (?,?,?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex,
                    identity["sid"],
                    identity["exe_path"].casefold(),
                    identity["sha256"],
                    name,
                    datetime.now(UTC).isoformat(),
                    channel,
                    json.dumps(identity["file_identity"]),
                ),
            )

    # list_permissions(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: list[dict[str, str]].
    def list_permissions(self) -> list[dict[str, str]]:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self.lock, self.connection() as db:
            # 아래 함수()의 반환값을 rows에 대입합니다.
            rows = db.execute(
                "SELECT id,name,path,sha256 FROM approvals WHERE sid=? ORDER BY name", (user_sid(),)
            ).fetchall()
        # result에 리스트(순서가 있고 수정 가능)을 대입합니다.
        result = []
        # for 반복문: 대상의 항목을 하나씩 (key, name, path, digest)에 대입하며 아래 블록을
        # 실행합니다.
        for key, name, path, digest in rows:
            # status에 문자열을 대입합니다.
            status = "실행 가능"
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
                # 사용합니다.
                with locked_identity(Path(path)) as identity:
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: identity['sha256'] !=
                    # digest.
                    if identity["sha256"] != digest:
                        # status에 문자열을 대입합니다.
                        status = "변경됨 — 재승인 필요"
            # (OSError, PolicyDenied)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
            # 담깁니다.
            except (OSError, PolicyDenied):
                # status에 문자열을 대입합니다.
                status = "실행 불가"
            # 리스트 끝에 항목 하나를 추가합니다.
            result.append({"id": key, "name": name, "path": path, "status": status})
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return result

    # invalidate_choices(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: session.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def invalidate_choices(self, session: str) -> None:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self.lock:
            # 오른쪽 식을 계산한 값을 self._choices에 대입합니다.
            # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
            self._choices = {k: v for k, v in self._choices.items() if v[1] != session}

    # refresh_catalog(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def refresh_catalog(self) -> None:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self.lock:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.dynamic.
            if self.dynamic:
                # discover_apps()의 반환값을 discovered에 대입합니다.
                discovered = discover_apps(self.limit)
                # self._catalog에 리스트(순서가 있고 수정 가능)을 대입합니다.
                self._catalog = []
                # self._catalog_metadata에 딕셔너리(키와 값의 쌍)을 대입합니다.
                self._catalog_metadata = {}
                # for 반복문: 대상의 항목을 하나씩 entry에 대입하며 아래 블록을 실행합니다.
                for entry in discovered:
                    # 언패킹: 오른쪽 결과를 순서대로 (name, path, source)에 나누어 담습니다.
                    name, path, source = entry.name, entry.path, entry.source
                    # 리스트 끝에 항목 하나를 추가합니다.
                    self._catalog.append((name, path))
                    # self._catalog_metadata[str(path).casefold()]에 딕셔너리(키와 값의 쌍)을
                    # 대입합니다.
                    self._catalog_metadata[str(path).casefold()] = {
                        "name": name, "source": source, "path": str(path),
                        "aliases": [name, path.stem], "file_identity": None,
                        "last_seen": datetime.now(UTC).isoformat(),
                    }
                # 오른쪽 식을 계산한 값을 self._expires에 대입합니다.
                self._expires = time.monotonic() + self.ttl

    # manage(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: command.
    # 반환 타입 힌트: 문자열(str).
    def manage(self, command: str) -> str:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not command.startswith('/apps revoke
        # ').
        if not command.startswith("/apps revoke "):
            # self.list_permissions()의 반환값을 rows에 대입합니다.
            rows = self.list_permissions()
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return "\n".join(
                f"{row['name']}: {row['path']} ({row['status']})\n취소: /apps revoke {row['id']}"
                for row in rows
            ) or "저장된 실행 허용 앱이 없습니다."
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self.lock, self.connection() as db:
            # command.removeprefix('/apps revoke ').strip()의 반환값을 key에 대입합니다.
            key = command.removeprefix("/apps revoke ").strip()
            # 오른쪽 식을 계산한 값을 count에 대입합니다.
            count = db.execute(
                "DELETE FROM approvals WHERE sid=? AND id=?", (user_sid(), key)
            ).rowcount
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
            return "실행 허용을 취소했습니다." if count else "허용 기록을 찾지 못했습니다."

    # resolve(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: query, configured, session, explicit.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: dict[str, Any].
    def resolve(
        self, query: str, configured: dict[str, Path], session: str, *, explicit: bool
    ) -> dict[str, Any]:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self.lock:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: query.startswith('choice:').
            if query.startswith("choice:"):
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not explicit.
                if not explicit:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise PolicyDenied("후보 선택은 사용자 명령으로만 가능합니다.")
                # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를
                # 처리합니다.
                try:
                    # 언패킹: 오른쪽 결과를 순서대로 (_, token, number)에 나누어 담습니다.
                    _, token, number = query.split(":")
                    # 언패킹: 오른쪽 결과를 순서대로 (expires, owner, choices)에 나누어 담습니다.
                    expires, owner, choices = self._choices[token]
                    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
                    if owner != session or time.monotonic() >= expires or int(number) < 1:
                        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                        # 이동합니다.
                        raise ValueError
                    # 오른쪽 식을 계산한 값을 chosen에 대입합니다.
                    chosen = choices[int(number) - 1]
                    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
                    # 사용합니다.
                    with locked_identity(Path(chosen["exe_path"])) as current:
                        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: any((current[k] !=
                        # chosen[k] for k in
                        # current)).
                        if any(current[k] != chosen[k] for k in current):
                            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                            # 이동합니다.
                            raise ValueError
                    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                    return {**chosen, "choice_token": token}
                # (ValueError, KeyError, IndexError)를 잡아 처리합니다. as 뒤의 이름에는 발생한
                # 예외 객체가 담깁니다.
                except (ValueError, KeyError, IndexError):
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise PolicyDenied(
                        "후보 선택이 만료되거나 앱이 변경됐습니다. 다시 요청하세요."
                    ) from None
            # aliases에 딕셔너리(키와 값의 쌍)을 대입합니다.
            aliases = {
                "카톡": "kakaotalk",
                "카카오톡": "kakaotalk",
                "디스코드": "discord",
                "메모장": "notepad",
                "계산기": "calc",
            }
            # aliases.get()의 반환값을 key에 대입합니다.
            key = aliases.get(query.casefold(), query.casefold())
            # 오른쪽 식을 계산한 값을 entries에 대입합니다.
            # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
            entries = [(name, path) for name, path in configured.items() if name.casefold() == key]
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not entries and self.dynamic.
            if not entries and self.dynamic:
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: time.monotonic() >=
                # self._expires.
                if time.monotonic() >= self._expires:
                    # self.refresh_catalog()을 호출해 작업을 수행합니다.
                    self.refresh_catalog()
                # 오른쪽 식을 계산한 값을 entries에 대입합니다.
                # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
                entries = [
                    (name, path)
                    for name, path in self._catalog
                    if key in {name.casefold(), path.stem.casefold()}
                ]
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not entries.
                if not entries:
                    # self._expires에 숫자 등 고정된 값을 대입합니다.
                    self._expires = 0
                    # self.refresh_catalog()을 호출해 작업을 수행합니다.
                    self.refresh_catalog()
                    # 오른쪽 식을 계산한 값을 entries에 대입합니다.
                    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로
                    # 모읍니다.
                    entries = [
                        (n, p) for n, p in self._catalog if key in {n.casefold(), p.stem.casefold()}
                    ]
            # candidates에 딕셔너리(키와 값의 쌍)을 대입합니다.
            candidates: dict[str, dict[str, Any]] = {}
            # for 반복문: 대상의 항목을 하나씩 (name, path)에 대입하며 아래 블록을 실행합니다.
            for name, path in entries:
                # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를
                # 처리합니다.
                try:
                    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
                    # 사용합니다.
                    with locked_identity(path) as identity:
                        # candidates[str(path.resolve()).casefold()]에 딕셔너리(키와 값의 쌍)을
                        # 대입합니다.
                        candidates[str(path.resolve()).casefold()] = {"app": name, **identity}
                        # self._catalog_metadata.get()의 반환값을 metadata에 대입합니다.
                        metadata = self._catalog_metadata.get(str(path).casefold())
                        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: metadata is not None.
                        if metadata is not None:
                            # metadata.update()을 호출해 작업을 수행합니다.
                            metadata.update(identity)
                # (OSError, PolicyDenied)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
                # 담깁니다.
                except (OSError, PolicyDenied):
                    # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                    continue
            # list()의 반환값을 choices에 대입합니다.
            choices = list(candidates.values())
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not choices.
            if not choices:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise PolicyDenied(
                    "실행 가능한 앱을 찾지 못했습니다. 설치 상태와 이름을 확인하세요."
                )
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(choices) > 1.
            if len(choices) > 1:
                # 오른쪽 식을 계산한 값을 token에 대입합니다.
                token = uuid.uuid4().hex
                # 오른쪽 식을 계산한 값을 self._choices에 대입합니다.
                # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
                self._choices = {k: v for k, v in self._choices.items() if v[0] > time.monotonic()}
                # self._choices[token]에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
                self._choices[token] = (time.monotonic() + 120, session, choices[:10])
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise PolicyDenied(
                    "앱 후보를 선택하세요:\n"
                    + "\n".join(
                        f"{i}. {x['app']} ({x['exe_path']})\n/open_app choice:{token}:{i}"
                        for i, x in enumerate(choices[:10], 1)
                    )
                )
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return choices[0]

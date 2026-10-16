# 파이썬 공부 | scripts/app/safety/processes.py
# Windows 프로세스의 신원을 확인하고 지정된 프로세스를 종료합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Windows process identities and handle-bound application termination."""

from __future__ import annotations

import ctypes as c
import os
from ctypes import wintypes as w
from pathlib import Path
from typing import Any

from app.core.errors import PolicyDenied


# WindowsProcesses: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class WindowsProcesses:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # c.WinDLL()의 반환값을 self.k에 대입합니다.
        self.k = c.WinDLL("kernel32", use_last_error=True)
        # c.WinDLL()의 반환값을 self.a에 대입합니다.
        self.a = c.WinDLL("advapi32", use_last_error=True)
        # c.WinDLL()의 반환값을 self.u에 대입합니다.
        self.u = c.WinDLL("user32", use_last_error=True)
        # self.k.OpenProcess.argtypes에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        # 오른쪽 식을 계산한 값을 self.k.OpenProcess.restype에 대입합니다.
        self.k.OpenProcess.restype = w.HANDLE
        # self.k.CloseHandle.argtypes에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.k.CloseHandle.argtypes = [w.HANDLE]
        # self.k.QueryFullProcessImageNameW.argtypes에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.k.QueryFullProcessImageNameW.argtypes = [
            w.HANDLE,
            w.DWORD,
            w.LPWSTR,
            c.POINTER(w.DWORD),
        ]
        # 오른쪽 식을 계산한 값을 self.k.GetProcessTimes.argtypes에 대입합니다.
        self.k.GetProcessTimes.argtypes = [w.HANDLE] + [c.POINTER(w.FILETIME)] * 4
        # self.k.WaitForSingleObject.argtypes에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        # self.k.TerminateProcess.argtypes에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.k.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        # self.a.OpenProcessToken.argtypes에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.a.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
        # self.a.GetTokenInformation.argtypes에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.a.GetTokenInformation.argtypes = [
            w.HANDLE,
            c.c_int,
            w.LPVOID,
            w.DWORD,
            c.POINTER(w.DWORD),
        ]
        # self.a.EqualSid.argtypes에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.a.EqualSid.argtypes = [w.LPVOID, w.LPVOID]
        # self.u.PostMessageW.argtypes에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.u.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        # self.u.GetWindowThreadProcessId.argtypes에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.u.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
        # c.WINFUNCTYPE()의 반환값을 self.callback에 대입합니다.
        self.callback = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        # self.u.EnumWindows.argtypes에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.u.EnumWindows.argtypes = [self.callback, w.LPARAM]

    # open(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: pid, terminate.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 어떤 타입이든 허용(Any).
    def open(self, pid: int, *, terminate: bool = False) -> Any:
        # self.k.OpenProcess()의 반환값을 handle에 대입합니다.
        handle = self.k.OpenProcess(0x1000 | 0x100000 | int(terminate), False, pid)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not handle.
        if not handle:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("프로세스 접근 권한을 확인할 수 없습니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return handle

    # token(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: handle, kind.
    # 반환 타입 힌트: 어떤 타입이든 허용(Any).
    def token(self, handle: Any, kind: int) -> Any:
        # w.HANDLE()의 반환값을 token에 대입합니다.
        token = w.HANDLE()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self.a.OpenProcessToken(handle, 8,
        # c.byref(token)).
        if not self.a.OpenProcessToken(handle, 8, c.byref(token)):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("프로세스 소유자를 확인할 수 없습니다.")
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # w.DWORD()의 반환값을 size에 대입합니다.
            size = w.DWORD()
            # self.a.GetTokenInformation()을 호출해 작업을 수행합니다.
            self.a.GetTokenInformation(token, kind, None, 0, c.byref(size))
            # c.create_string_buffer()의 반환값을 buf에 대입합니다.
            buf = c.create_string_buffer(size.value)
            # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
            if not self.a.GetTokenInformation(token, kind, buf, size, c.byref(size)):
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise PolicyDenied("프로세스 토큰 확인에 실패했습니다.")
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return buf
        # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
        finally:
            # self.k.CloseHandle()을 호출해 작업을 수행합니다.
            self.k.CloseHandle(token)

    # identity(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: handle, pid.
    # 반환 타입 힌트: dict[str, Any].
    def identity(self, handle: Any, pid: int) -> dict[str, Any]:
        # c.create_unicode_buffer()의 반환값을 path에 대입합니다.
        path = c.create_unicode_buffer(32768)
        # w.DWORD()의 반환값을 size에 대입합니다.
        size = w.DWORD(len(path))
        # 오른쪽 식을 계산한 값을 times에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        times = [w.FILETIME() for _ in range(4)]
        # w.DWORD()의 반환값을 session에 대입합니다.
        session = w.DWORD()
        # w.DWORD()의 반환값을 current_session에 대입합니다.
        current_session = w.DWORD()
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not self.k.QueryFullProcessImageNameW(handle, 0, path, c.byref(size)):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("실행 파일 경로 확인에 실패했습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self.k.GetProcessTimes(handle,
        # *(c.byref(t) for t in
        # times)).
        if not self.k.GetProcessTimes(handle, *(c.byref(t) for t in times)):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("프로세스 생성 시각 확인에 실패했습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self.k.ProcessIdToSessionId(pid,
        # c.byref(session)).
        if not self.k.ProcessIdToSessionId(pid, c.byref(session)):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("프로세스 세션 확인에 실패했습니다.")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not self.k.ProcessIdToSessionId(os.getpid(), c.byref(current_session)):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("현재 세션 확인에 실패했습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: session.value == 0 or session.value !=
        # current_session.value.
        if session.value == 0 or session.value != current_session.value:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("다른 세션의 앱은 종료할 수 없습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: pid in {os.getpid(), os.getppid()}.
        if pid in {os.getpid(), os.getppid()}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("Jarvis 실행 프로세스는 종료할 수 없습니다.")
        # self.open()의 반환값을 current에 대입합니다.
        current = self.open(os.getpid())
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # self.token()의 반환값을 owner에 대입합니다.
            owner = self.token(handle, 1)
            # self.token()의 반환값을 mine에 대입합니다.
            mine = self.token(current, 1)
            # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
            if not self.a.EqualSid(
                c.cast(owner, c.POINTER(w.LPVOID))[0], c.cast(mine, c.POINTER(w.LPVOID))[0]
            ):
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise PolicyDenied("다른 사용자의 앱은 종료할 수 없습니다.")
        # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
        finally:
            # self.k.CloseHandle()을 호출해 작업을 수행합니다.
            self.k.CloseHandle(current)
        # self.token()의 반환값을 elevation에 대입합니다.
        elevation = self.token(handle, 20)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: c.cast(elevation,
        # c.POINTER(w.DWORD))[0].
        if c.cast(elevation, c.POINTER(w.DWORD))[0]:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("관리자 권한으로 실행된 앱은 종료하지 않습니다.")
        # Path(path.value).resolve()의 반환값을 exe에 대입합니다.
        exe = Path(path.value).resolve()
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if exe.name.lower() in {
            "explorer.exe",
            "python.exe",
            "pythonw.exe",
            "jarvis.exe",
            "ollama.exe",
            "lsass.exe",
            "csrss.exe",
            "winlogon.exe",
            "services.exe",
            "svchost.exe",
            "smss.exe",
        }:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("보호 대상 프로세스입니다.")
        # exe.stat()의 반환값을 stat에 대입합니다.
        stat = exe.stat()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return {
            "pid": pid,
            "created": times[0].dwHighDateTime << 32 | times[0].dwLowDateTime,
            "exe_path": str(exe),
            "session": session.value,
            "file_identity": [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns],
        }

    # snapshot(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: exe.
    # 반환 타입 힌트: list[dict[str, Any]].
    def snapshot(self, exe: Path) -> list[dict[str, Any]]:
        # w.DWORD * 65536()의 반환값을 ids에 대입합니다.
        ids = (w.DWORD * 65536)()
        # w.DWORD()의 반환값을 needed에 대입합니다.
        needed = w.DWORD()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self.k.K32EnumProcesses(ids,
        # c.sizeof(ids),
        # c.byref(needed)).
        if not self.k.K32EnumProcesses(ids, c.sizeof(ids), c.byref(needed)):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("실행 중인 앱을 확인할 수 없습니다.")
        # matches에 리스트(순서가 있고 수정 가능)을 대입합니다.
        matches = []
        # for 반복문: 대상의 항목을 하나씩 pid에 대입하며 아래 블록을 실행합니다.
        for pid in ids[: needed.value // c.sizeof(w.DWORD)]:
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # self.open()의 반환값을 handle에 대입합니다.
                handle = self.open(pid)
            # PolicyDenied를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
            except PolicyDenied:
                # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                continue
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # c.create_unicode_buffer()의 반환값을 path에 대입합니다.
                path = c.create_unicode_buffer(32768)
                # w.DWORD()의 반환값을 size에 대입합니다.
                size = w.DWORD(len(path))
                # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
                if (
                    self.k.QueryFullProcessImageNameW(handle, 0, path, c.byref(size))
                    and Path(path.value).resolve() == exe.resolve()
                ):
                    # 리스트 끝에 항목 하나를 추가합니다.
                    matches.append(self.identity(handle, pid))
            # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
            finally:
                # self.k.CloseHandle()을 호출해 작업을 수행합니다.
                self.k.CloseHandle(handle)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return sorted(matches, key=lambda item: item["pid"])

    # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: targets, force, timeout_s.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 참/거짓(bool).
    def close(self, targets: list[dict[str, Any]], *, force: bool, timeout_s: float) -> bool:
        # handles에 리스트(순서가 있고 수정 가능)을 대입합니다.
        handles = []
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # for 반복문: 대상의 항목을 하나씩 target에 대입하며 아래 블록을 실행합니다.
            for target in targets:
                # self.open()의 반환값을 handle에 대입합니다.
                handle = self.open(target["pid"], terminate=force)
                # 리스트 끝에 항목 하나를 추가합니다.
                handles.append(handle)
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.identity(handle,
                # target['pid']) != target.
                if self.identity(handle, target["pid"]) != target:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise PolicyDenied("승인 후 종료 대상이 변경되었습니다. 다시 요청하세요.")
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: force.
            if force:
                # for 반복문: 대상의 항목을 하나씩 handle에 대입하며 아래 블록을 실행합니다.
                for handle in handles:
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not
                    # self.k.TerminateProcess(handle, 1).
                    if not self.k.TerminateProcess(handle, 1):
                        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                        # 이동합니다.
                        raise PolicyDenied("프로세스 종료 요청에 실패했습니다.")
            # 앞선 조건이 거짓이면 이 블록을 실행합니다.
            else:
                # 오른쪽 식을 계산한 값을 pids에 대입합니다.
                # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
                pids = {target["pid"] for target in targets}

                # visit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
                # 입력: hwnd, unused.
                # 반환 타입 힌트: 참/거짓(bool).
                def visit(hwnd: Any, unused: Any) -> bool:
                    # w.DWORD()의 반환값을 pid에 대입합니다.
                    pid = w.DWORD()
                    # self.u.GetWindowThreadProcessId()을 호출해 작업을 수행합니다.
                    self.u.GetWindowThreadProcessId(hwnd, c.byref(pid))
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: pid.value in pids.
                    if pid.value in pids:
                        # self.u.PostMessageW()을 호출해 작업을 수행합니다.
                        self.u.PostMessageW(hwnd, 0x0010, 0, 0)
                    # True을 반환하고 이 함수의 실행을 끝냅니다.
                    return True

                # self.callback()의 반환값을 callback에 대입합니다.
                callback = self.callback(visit)
                # self.u.EnumWindows()을 호출해 작업을 수행합니다.
                self.u.EnumWindows(callback, 0)
            # int()의 반환값을 wait_ms에 대입합니다.
            wait_ms = int(max(0, min(timeout_s, 5)) * 1000 / max(1, len(handles)))
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return all(self.k.WaitForSingleObject(handle, wait_ms) == 0 for handle in handles)
        # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
        finally:
            # for 반복문: 대상의 항목을 하나씩 handle에 대입하며 아래 블록을 실행합니다.
            for handle in handles:
                # self.k.CloseHandle()을 호출해 작업을 수행합니다.
                self.k.CloseHandle(handle)


# snapshot_app(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: exe.
# 반환 타입 힌트: list[dict[str, Any]].
def snapshot_app(exe: Path) -> list[dict[str, Any]]:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return WindowsProcesses().snapshot(exe)
    # OSError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except OSError as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied("앱 종료 대상 확인에 실패했습니다.") from error

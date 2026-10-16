# 파이썬 공부 | scripts/app/voice/interrupt_hotkey.py
# 단축키 입력을 받아 음성 출력을 취소할 수 있게 합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Optional global hotkey that cancels TTS during barge-in monitoring."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


# InterruptHotkeyMonitor: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class InterruptHotkeyMonitor(Protocol):
    # poll(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 참/거짓(bool).
    def poll(self) -> bool: ...

    # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def close(self) -> None: ...


# 오른쪽 식을 계산한 값을 InterruptHotkeyFactory에 대입합니다.
InterruptHotkeyFactory = Callable[[], InterruptHotkeyMonitor]


# ParsedHotkey: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class ParsedHotkey:
    # modifiers: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    modifiers: int
    # vk: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    vk: int
    # label: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    label: str


# _MOD_ALT에 숫자 등 고정된 값을 대입합니다.
_MOD_ALT = 0x0001
# _MOD_CONTROL에 숫자 등 고정된 값을 대입합니다.
_MOD_CONTROL = 0x0002
# _MOD_SHIFT에 숫자 등 고정된 값을 대입합니다.
_MOD_SHIFT = 0x0004
# _MOD_WIN에 숫자 등 고정된 값을 대입합니다.
_MOD_WIN = 0x0008
# _WM_HOTKEY에 숫자 등 고정된 값을 대입합니다.
_WM_HOTKEY = 0x0312
# _HOTKEY_ID에 숫자 등 고정된 값을 대입합니다.
_HOTKEY_ID = 0x6A01
# _PM_REMOVE에 숫자 등 고정된 값을 대입합니다.
_PM_REMOVE = 0x0001


# _initial_thread_error(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: BaseException | None.
def _initial_thread_error() -> BaseException | None:
    # None을 반환하고 이 함수의 실행을 끝냅니다.
    return None


# parse_hotkey(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: spec.
# 반환 타입 힌트: ParsedHotkey.
def parse_hotkey(spec: str) -> ParsedHotkey:
    # 오른쪽 식을 계산한 값을 parts에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    parts = [part.strip().casefold() for part in spec.split("+") if part.strip()]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not parts.
    if not parts:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("hotkey must not be empty")
    # modifiers에 숫자 등 고정된 값을 대입합니다.
    modifiers = 0
    # key을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    key: str | None = None
    # for 반복문: 대상의 항목을 하나씩 part에 대입하며 아래 블록을 실행합니다.
    for part in parts:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: part in {'ctrl', 'control'}.
        if part in {"ctrl", "control"}:
            # 복합 대입: 기존 값에 오른쪽 값을 합친 결과를 다시 저장합니다.
            modifiers |= _MOD_CONTROL
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: part == 'alt'.
        elif part == "alt":
            # 복합 대입: 기존 값에 오른쪽 값을 합친 결과를 다시 저장합니다.
            modifiers |= _MOD_ALT
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: part == 'shift'.
        elif part == "shift":
            # 복합 대입: 기존 값에 오른쪽 값을 합친 결과를 다시 저장합니다.
            modifiers |= _MOD_SHIFT
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: part in {'win', 'windows', 'super',
        # 'meta'}.
        elif part in {"win", "windows", "super", "meta"}:
            # 복합 대입: 기존 값에 오른쪽 값을 합친 결과를 다시 저장합니다.
            modifiers |= _MOD_WIN
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: key is None and len(part) == 1 and
        # part.isalnum().
        elif key is None and len(part) == 1 and part.isalnum():
            # 오른쪽 식을 계산한 값을 key에 대입합니다.
            key = part
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError(f"unsupported hotkey token: {part}")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: key is None.
    if key is None:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("hotkey must include one letter or digit key")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: modifiers == 0.
    if modifiers == 0:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("hotkey must include at least one modifier")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return ParsedHotkey(modifiers, ord(key.upper()), "+".join(parts))


# NullInterruptHotkey: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class NullInterruptHotkey:
    # poll(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 참/거짓(bool).
    def poll(self) -> bool:
        # False을 반환하고 이 함수의 실행을 끝냅니다.
        return False

    # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def close(self) -> None:
        # None을 반환하고 이 함수의 실행을 끝냅니다.
        return None


# WindowsInterruptHotkey: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class WindowsInterruptHotkey:
    """Register one process-wide hotkey and expose edge-triggered poll()."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: spec.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, spec: str) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: sys.platform != 'win32'.
        if sys.platform != "win32":
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise RuntimeError("WindowsInterruptHotkey requires win32")
        import ctypes
        from ctypes import wintypes

        # parse_hotkey()의 반환값을 self._parsed에 대입합니다.
        self._parsed = parse_hotkey(spec)
        # 오른쪽 식을 계산한 값을 self._user32에 대입합니다.
        self._user32 = ctypes.windll.user32
        # threading.Event()의 반환값을 self._fired에 대입합니다.
        self._fired = threading.Event()
        # threading.Event()의 반환값을 self._stop에 대입합니다.
        self._stop = threading.Event()
        # threading.Event()의 반환값을 self._thread_ready에 대입합니다.
        self._thread_ready = threading.Event()
        # _initial_thread_error()의 반환값을 self._error에 대입합니다.
        self._error = _initial_thread_error()
        # wintypes.MSG()의 반환값을 self._msg에 대입합니다.
        self._msg = wintypes.MSG()
        # threading.Thread()의 반환값을 self._thread에 대입합니다.
        self._thread = threading.Thread(
            target=self._run,
            name="jarvis-interrupt-hotkey",
            daemon=True,
        )
        # self._thread.start()을 호출해 작업을 수행합니다.
        self._thread.start()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not
        # self._thread_ready.wait(timeout=3).
        if not self._thread_ready.wait(timeout=3):
            # 사용하던 연결이나 자원을 닫습니다.
            self.close()
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise RuntimeError("interrupt hotkey thread failed to start")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._error is not None.
        if self._error is not None:
            # 사용하던 연결이나 자원을 닫습니다.
            self.close()
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise RuntimeError(str(self._error)) from self._error

    # poll(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 참/거짓(bool).
    def poll(self) -> bool:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._fired.is_set()

    # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def close(self) -> None:
        # self._stop.set()을 호출해 작업을 수행합니다.
        self._stop.set()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._thread.is_alive().
        if self._thread.is_alive():
            # join을 호출합니다. 문자열에서는 조각 결합, 스레드에서는 종료 대기를 뜻합니다.
            self._thread.join(timeout=2)

    # _run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _run(self) -> None:
        import ctypes

        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
            if not self._user32.RegisterHotKey(
                None,
                _HOTKEY_ID,
                self._parsed.modifiers,
                self._parsed.vk,
            ):
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise OSError(f"RegisterHotKey failed for {self._parsed.label}")
        # BaseException를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except BaseException as error:
            # 오른쪽 식을 계산한 값을 self._error에 대입합니다.
            self._error = error
            # self._thread_ready.set()을 호출해 작업을 수행합니다.
            self._thread_ready.set()
            # 이 함수를 여기서 끝냅니다. 값을 쓰지 않은 return은 None을 반환합니다.
            return
        # self._thread_ready.set()을 호출해 작업을 수행합니다.
        self._thread_ready.set()
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
            while not self._stop.is_set():
                # self._user32.PeekMessageW()의 반환값을 has_message에 대입합니다.
                has_message = self._user32.PeekMessageW(
                    ctypes.byref(self._msg),
                    None,
                    0,
                    0,
                    _PM_REMOVE,
                )
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: has_message and
                # self._msg.message == _WM_HOTKEY.
                if has_message and self._msg.message == _WM_HOTKEY:
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._msg.wParam ==
                    # _HOTKEY_ID.
                    if self._msg.wParam == _HOTKEY_ID:
                        # self._fired.set()을 호출해 작업을 수행합니다.
                        self._fired.set()
                        # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                        break
                # 앞선 조건이 거짓이면 이 블록을 실행합니다.
                else:
                    # self._stop.wait()을 호출해 작업을 수행합니다.
                    self._stop.wait(0.05)
        # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
        finally:
            # self._user32.UnregisterHotKey()을 호출해 작업을 수행합니다.
            self._user32.UnregisterHotKey(None, _HOTKEY_ID)


# create_interrupt_hotkey(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: spec.
# 반환 타입 힌트: InterruptHotkeyMonitor.
def create_interrupt_hotkey(spec: str | None) -> InterruptHotkeyMonitor:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not spec.
    if not spec:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return NullInterruptHotkey()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: sys.platform != 'win32'.
    if sys.platform != "win32":
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return NullInterruptHotkey()
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return WindowsInterruptHotkey(spec)
    # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except Exception:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return NullInterruptHotkey()

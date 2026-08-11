"""Optional global hotkey that cancels TTS during barge-in monitoring."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class InterruptHotkeyMonitor(Protocol):
    def poll(self) -> bool: ...

    def close(self) -> None: ...


InterruptHotkeyFactory = Callable[[], InterruptHotkeyMonitor]


@dataclass(frozen=True, slots=True)
class ParsedHotkey:
    modifiers: int
    vk: int
    label: str


_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_WIN = 0x0008
_WM_HOTKEY = 0x0312
_HOTKEY_ID = 0x6A01
_PM_REMOVE = 0x0001


def _initial_thread_error() -> BaseException | None:
    return None


def parse_hotkey(spec: str) -> ParsedHotkey:
    parts = [part.strip().casefold() for part in spec.split("+") if part.strip()]
    if not parts:
        raise ValueError("hotkey must not be empty")
    modifiers = 0
    key: str | None = None
    for part in parts:
        if part in {"ctrl", "control"}:
            modifiers |= _MOD_CONTROL
        elif part == "alt":
            modifiers |= _MOD_ALT
        elif part == "shift":
            modifiers |= _MOD_SHIFT
        elif part in {"win", "windows", "super", "meta"}:
            modifiers |= _MOD_WIN
        elif key is None and len(part) == 1 and part.isalnum():
            key = part
        else:
            raise ValueError(f"unsupported hotkey token: {part}")
    if key is None:
        raise ValueError("hotkey must include one letter or digit key")
    if modifiers == 0:
        raise ValueError("hotkey must include at least one modifier")
    return ParsedHotkey(modifiers, ord(key.upper()), "+".join(parts))


class NullInterruptHotkey:
    def poll(self) -> bool:
        return False

    def close(self) -> None:
        return None


class WindowsInterruptHotkey:
    """Register one process-wide hotkey and expose edge-triggered poll()."""

    def __init__(self, spec: str) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WindowsInterruptHotkey requires win32")
        import ctypes
        from ctypes import wintypes

        self._parsed = parse_hotkey(spec)
        self._user32 = ctypes.windll.user32
        self._fired = threading.Event()
        self._stop = threading.Event()
        self._thread_ready = threading.Event()
        self._error = _initial_thread_error()
        self._msg = wintypes.MSG()
        self._thread = threading.Thread(
            target=self._run,
            name="jarvis-interrupt-hotkey",
            daemon=True,
        )
        self._thread.start()
        if not self._thread_ready.wait(timeout=3):
            self.close()
            raise RuntimeError("interrupt hotkey thread failed to start")
        if self._error is not None:
            self.close()
            raise RuntimeError(str(self._error)) from self._error

    def poll(self) -> bool:
        return self._fired.is_set()

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        import ctypes

        try:
            if not self._user32.RegisterHotKey(
                None,
                _HOTKEY_ID,
                self._parsed.modifiers,
                self._parsed.vk,
            ):
                raise OSError(f"RegisterHotKey failed for {self._parsed.label}")
        except BaseException as error:
            self._error = error
            self._thread_ready.set()
            return
        self._thread_ready.set()
        try:
            while not self._stop.is_set():
                has_message = self._user32.PeekMessageW(
                    ctypes.byref(self._msg),
                    None,
                    0,
                    0,
                    _PM_REMOVE,
                )
                if has_message and self._msg.message == _WM_HOTKEY:
                    if self._msg.wParam == _HOTKEY_ID:
                        self._fired.set()
                        break
                else:
                    self._stop.wait(0.05)
        finally:
            self._user32.UnregisterHotKey(None, _HOTKEY_ID)


def create_interrupt_hotkey(spec: str | None) -> InterruptHotkeyMonitor:
    if not spec:
        return NullInterruptHotkey()
    if sys.platform != "win32":
        return NullInterruptHotkey()
    try:
        return WindowsInterruptHotkey(spec)
    except Exception:
        return NullInterruptHotkey()

"""Injectable clock, sleeper, and randomness protocols with system implementations."""

from __future__ import annotations

import math
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol

KST = timezone(timedelta(hours=9), name="KST")


class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic_ms(self) -> int: ...


class Sleeper(Protocol):
    def sleep(self, seconds: float) -> None: ...


class RandomSource(Protocol):
    def uniform(self, low: float, high: float) -> float: ...


class SystemClock:
    """Wall and monotonic time for production code."""

    def now(self) -> datetime:
        return datetime.now(tz=KST)

    def monotonic_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000


class SystemSleeper:
    """Production sleep implementation with finite-duration validation."""

    def sleep(self, seconds: float) -> None:
        if seconds < 0 or not math.isfinite(seconds):
            raise ValueError("sleep duration must be finite and non-negative")
        time.sleep(seconds)


class SystemRandom:
    """Cryptographically strong jitter source without module-global random state."""

    def __init__(self) -> None:
        self._random = secrets.SystemRandom()

    def uniform(self, low: float, high: float) -> float:
        if not math.isfinite(low) or not math.isfinite(high) or low > high:
            raise ValueError("random range must be finite and ordered")
        return self._random.uniform(low, high)

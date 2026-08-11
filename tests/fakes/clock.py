"""Deterministic implementations of the core time and randomness protocols."""

from __future__ import annotations

from datetime import datetime, timedelta


class FrozenClock:
    def __init__(self, current: datetime) -> None:
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._current = current

    def now(self) -> datetime:
        return self._current

    def monotonic_ms(self) -> int:
        return int(self._current.timestamp() * 1000)

    def advance(self, **delta: float) -> None:
        self._current += timedelta(**delta)


class SteppingClock(FrozenClock):
    def __init__(self, current: datetime, *, step: timedelta) -> None:
        super().__init__(current)
        if step.total_seconds() < 0:
            raise ValueError("step cannot be negative")
        self._step = step

    def now(self) -> datetime:
        current = super().now()
        self.advance(seconds=self._step.total_seconds())
        return current


class ImmediateSleeper:
    def __init__(self) -> None:
        self.durations: list[float] = []

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("sleep duration cannot be negative")
        self.durations.append(seconds)


class FixedRandom:
    def __init__(self, value: float) -> None:
        self.value = value
        self.calls: list[tuple[float, float]] = []

    def uniform(self, low: float, high: float) -> float:
        if low > high or not low <= self.value <= high:
            raise ValueError("fixed value is outside the requested range")
        self.calls.append((low, high))
        return self.value

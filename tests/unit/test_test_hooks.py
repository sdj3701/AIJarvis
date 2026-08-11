"""Safety tests for development-only crash hooks."""

from __future__ import annotations

import pytest

from app.core.test_hooks import CrashTestHook

pytestmark = pytest.mark.phase1


def test_crash_hook_is_inert_in_production_mode() -> None:
    exit_codes: list[int] = []
    hook = CrashTestHook("user.input", enabled=False, terminate=exit_codes.append)

    hook.after("user.input")

    assert hook.enabled is False
    assert exit_codes == []


def test_crash_hook_requires_exact_allowlisted_point() -> None:
    exit_codes: list[int] = []
    hook = CrashTestHook("unknown", enabled=True, terminate=exit_codes.append)

    hook.after("unknown")

    assert hook.enabled is False
    assert exit_codes == []


def test_development_hook_terminates_only_at_selected_point() -> None:
    exit_codes: list[int] = []
    hook = CrashTestHook("llm.request", enabled=True, terminate=exit_codes.append)

    hook.after("user.input")
    hook.after("llm.request")

    assert hook.enabled is True
    assert exit_codes == [97]

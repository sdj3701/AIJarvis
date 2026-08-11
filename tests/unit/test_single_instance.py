from __future__ import annotations

from pathlib import Path

import pytest

from app.ui.single_instance import AlreadyRunningError, SingleInstanceLock


def test_second_instance_is_rejected_until_first_releases(tmp_path: Path) -> None:
    path = tmp_path / "state" / "jarvis.lock"
    first = SingleInstanceLock(path)
    second = SingleInstanceLock(path)
    first.acquire()

    with pytest.raises(AlreadyRunningError, match="이미 실행 중") as captured:
        second.acquire()

    assert captured.value.user_message == "Jarvis가 이미 실행 중입니다."
    assert first.acquired
    first.release()
    second.acquire()
    assert second.acquired
    second.release()


def test_single_instance_context_releases_after_error(tmp_path: Path) -> None:
    path = tmp_path / "jarvis.lock"

    with pytest.raises(RuntimeError, match="boom"), SingleInstanceLock(path):
        raise RuntimeError("boom")

    with SingleInstanceLock(path) as lock:
        assert lock.acquired

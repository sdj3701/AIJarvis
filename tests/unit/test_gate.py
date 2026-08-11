"""Phase 게이트 증거의 작업 트리 결합 검증."""

from __future__ import annotations

from subprocess import CompletedProcess

import pytest

from scripts import gate

pytestmark = pytest.mark.phase0


def test_worktree_changes_ignore_only_gate_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = CompletedProcess(
        args=["git"],
        returncode=0,
        stdout=(
            " M app/rag/fetcher.py\n"
            "?? artifacts/gates/phase5-20260811.json\n"
        ),
        stderr="",
    )
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: result)

    assert gate._worktree_changes() == (" M app/rag/fetcher.py",)

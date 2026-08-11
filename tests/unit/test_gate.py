"""Tests for phase-specific machine-readable gate evidence."""

from __future__ import annotations

import pytest

from scripts.gate import _phase_evidence

pytestmark = pytest.mark.phase1


def test_phase_zero_has_no_quantitative_metrics() -> None:
    metrics, notes = _phase_evidence(0, passed=True)

    assert metrics == []
    assert "Phase 0" in notes[0]


def test_phase_one_documents_twenty_crashes_and_manual_latency() -> None:
    metrics, notes = _phase_evidence(1, passed=True)

    assert metrics[0] == {
        "name": "recovery.input_loss",
        "value": 0,
        "threshold": 0,
        "ok": True,
        "note": "5개 종료 지점마다 4회씩, 총 20회 별도 프로세스 강제 종료",
    }
    assert metrics[1]["value"] is None
    assert metrics[1]["ok"] is None
    assert any("실제 로컬 모델" in note for note in notes)


def test_failed_phase_does_not_claim_zero_input_loss() -> None:
    metrics, _ = _phase_evidence(1, passed=False)

    assert metrics[0]["value"] is None
    assert metrics[0]["ok"] is False

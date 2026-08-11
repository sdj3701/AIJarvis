"""Forbidden destructive actions must never execute."""

from __future__ import annotations

import pytest

from tests.helpers.phase4_app import Phase4App, snapshot_tree

pytestmark = [pytest.mark.phase4, pytest.mark.security]


def test_delete_request_refused(phase4_app: Phase4App) -> None:
    before = snapshot_tree(phase4_app.data_root)
    outcome = phase4_app.chat.handle_turn("파일 삭제해줘")
    assert not outcome.ok
    assert snapshot_tree(phase4_app.data_root) == before
    assert any(record.get("event_type") == "policy.deny" for record in _events(phase4_app))


def test_unlisted_app_denied(phase4_app: Phase4App) -> None:
    outcome = phase4_app.chat.handle_turn("/open_app chrome")
    assert not outcome.ok
    last = phase4_app.audit()[-1]
    assert last["phase"] == "denied"


def _events(phase4_app: Phase4App) -> list:
    import json

    records = []
    for path in sorted((phase4_app.data_root / "logs").glob("events-*.jsonl")):
        records.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return records

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from app.config.loader import load_config
from app.config.models import SemanticSettings
from app.core.ids import new_id
from app.memory.store import RawRecord
from app.rag.semantic import SemanticMemory
from scripts.import_conversations import import_conversations
from tests.unit.test_semantic_memory import NOW, FakeEmbedder


def pair(question: str = "좋아하는 음식", answer: str = "파스타입니다.") -> list[RawRecord]:
    user = RawRecord(
        ts=NOW - timedelta(days=10), session_id=new_id("ses"), turn_id=new_id("turn"),
        role="user", content=question, channel="text", request_id=new_id("req"),
    )
    return [user, replace(user, role="assistant", content=answer, meta={"model": "legacy"})]


def write_log(raw: Path, records: list[RawRecord]) -> Path:
    raw.mkdir(exist_ok=True)
    path = raw / (new_id("ses") + ".jsonl")
    path.write_text("\n".join(json.dumps(r.as_dict()) for r in records), encoding="utf-8")
    return path


def test_preview_import_restart_and_retry(config_dir: Path, tmp_path: Path) -> None:
    privacy = load_config(config_dir).policies.privacy
    raw = tmp_path / "raw"
    records = pair()
    path = write_log(raw, records)
    original = path.read_bytes()
    embedder = FakeEmbedder()
    memory = SemanticMemory(tmp_path / "semantic.sqlite3", SemanticSettings(), embedder=embedder)
    preview = import_conversations(raw, memory, privacy, now=NOW)
    assert preview["eligible"] == 1
    assert not memory.path.exists()
    assert not embedder.calls
    embedder.offline = True
    result = import_conversations(raw, memory, privacy, now=NOW, apply=True)
    assert result["imported"] == 1
    assert memory.stats()["pending_vectors"] == 2
    embedder.offline = False
    result = import_conversations(raw, memory, privacy, now=NOW, apply=True)
    assert result["existing"] == 1
    assert result["imported"] == 0
    assert memory.stats()["conversation_vectors"] == 2
    assert memory.stats()["pending_vectors"] == 0
    reopened = SemanticMemory(memory.path, memory.settings, embedder=embedder)
    hit = reopened.recall("스파게티", now=NOW)[0]
    assert hit["turn_id"] == records[0].turn_id
    assert hit["created_at"] == records[1].ts.isoformat()
    assert hit["verified"] is False
    assert path.read_bytes() == original


@pytest.mark.parametrize("case,reason", [
    ("incomplete", "incomplete_or_ambiguous"),
    ("failed", "incomplete_or_ambiguous"),
    ("mismatched_request", "incomplete_or_ambiguous"),
    ("command", "commands"),
    ("expired", "outside_retention"),
    ("secret", "blocked"),
    ("masked_secret", "blocked"),
])
def test_ineligible_turns_are_not_imported(
    config_dir: Path, tmp_path: Path, case: str, reason: str,
) -> None:
    privacy = load_config(config_dir).policies.privacy
    records = pair()
    if case == "incomplete":
        records = records[:1]
    elif case == "failed":
        records.append(replace(records[0], role="system_note", meta={"status": "error"}))
    elif case == "mismatched_request":
        records[1] = replace(records[1], request_id=new_id("req"))
    elif case == "command":
        records[0] = replace(records[0], content="/recall forget turn_123")
    elif case == "expired":
        records = [replace(r, ts=NOW - timedelta(days=91)) for r in records]
    elif case == "secret":
        records[0] = replace(records[0], content="password=abcdefgh123456")
    elif case == "masked_secret":
        marker = privacy.mask.replacement.replace("{label}", "등록된 시크릿")
        records[0] = replace(records[0], content="기억해 " + marker)
    raw = tmp_path / "raw"
    write_log(raw, records)
    embedder = FakeEmbedder()
    memory = SemanticMemory(tmp_path / "semantic.sqlite3", SemanticSettings(), embedder=embedder)
    result = import_conversations(raw, memory, privacy, now=NOW, apply=True)
    assert result[reason] == 1
    assert result["imported"] == 0
    assert memory.stats()["turns"] == 0
    assert not embedder.calls


def test_damaged_file_is_reported_without_editing_logs(config_dir: Path, tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    path = write_log(raw, pair())
    path.write_text(path.read_text(encoding="utf-8") + '\n{"v":', encoding="utf-8")
    original = path.read_bytes()
    memory = SemanticMemory(tmp_path / "semantic.sqlite3", SemanticSettings(),
                            embedder=FakeEmbedder())
    result = import_conversations(raw, memory, load_config(config_dir).policies.privacy,
                                  now=NOW, apply=True)
    assert result["invalid_files"] == 1
    assert result["imported"] == 0
    assert path.read_bytes() == original

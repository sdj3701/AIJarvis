"""Tests for Hybrid RRF Search (FTS5 + 512D Vector + RRF)."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from app.config.loader import load_policies, load_settings
from app.core.ids import SystemIdFactory
from app.memory.migrations import initialize_database
from app.rag.indexer import DocumentIndexer

pytestmark = pytest.mark.phase3
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 14, 0, tzinfo=KST)


@pytest.fixture
def hybrid_indexer(tmp_path: Path) -> DocumentIndexer:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in ("settings", "tools", "privacy"):
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            config_dir / f"{name}.yaml",
        )
    settings_doc = yaml.safe_load((config_dir / "settings.yaml").read_text(encoding="utf-8"))
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True)
    settings_doc["paths"]["data_root"] = str(data_root)
    (config_dir / "settings.yaml").write_text(
        yaml.safe_dump(settings_doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    settings = load_settings(config_dir / "settings.yaml")
    policies = load_policies(
        config_dir / "tools.yaml",
        config_dir / "privacy.yaml",
        settings=settings,
    )
    docs_root = data_root / "docs"
    docs_root.mkdir(parents=True)

    # 1. Exact error code keyword document
    (docs_root / "error_codes.txt").write_text(
        "자비스 시스템 에러코드 ERR_STARK_007: 아크 리액터 출력 과부하 및 냉각수 부족 발생.",
        encoding="utf-8",
    )
    # 2. Semantic food preferences document
    (docs_root / "preferences.txt").write_text(
        "보스는 이탈리안 요리 중에서 특히 토마토 파스타와 화덕 피자를 아주 선호하십니다.",
        encoding="utf-8",
    )

    db = data_root / "memory" / "jarvis.sqlite3"
    initialize_database(db, created_at=NOW)
    return DocumentIndexer(
        database_path=db,
        docs_root=docs_root,
        settings=settings.rag,
        document_policy=policies.privacy.api_transmission.documents,
        ids=SystemIdFactory(),
    )


def test_hybrid_rrf_search_exact_and_semantic(hybrid_indexer: DocumentIndexer) -> None:
    # 1. Sync documents
    report = hybrid_indexer.sync()
    assert report.indexed == 2

    # 2. Exact Keyword Query (FTS5 + RRF)
    exact_hits = hybrid_indexer.search("ERR_STARK_007 리액터")
    assert len(exact_hits) >= 1
    assert "ERR_STARK_007" in exact_hits[0].text
    assert exact_hits[0].relative_path == "error_codes.txt"

    # 3. Semantic / Synonym Query (512D Vector + RRF)
    semantic_hits = hybrid_indexer.search("보스가 좋아하는 이태리 스파게티 요리")
    assert len(semantic_hits) >= 1
    assert "토마토 파스타" in semantic_hits[0].text
    assert semantic_hits[0].relative_path == "preferences.txt"

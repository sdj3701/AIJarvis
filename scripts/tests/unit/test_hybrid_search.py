# 파이썬 공부 | scripts/tests/unit/test_hybrid_search.py
# hybrid_search 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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
from app.rag.semantic import SemanticMemory

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase3
# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 14, 0, tzinfo=KST)


# hybrid_indexer(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: DocumentIndexer.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def hybrid_indexer(tmp_path: Path) -> DocumentIndexer:
    # 오른쪽 식을 계산한 값을 config_dir에 대입합니다.
    config_dir = tmp_path / "config"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    config_dir.mkdir()
    # for 반복문: 대상의 항목을 하나씩 name에 대입하며 아래 블록을 실행합니다.
    for name in ("settings", "tools", "privacy"):
        # shutil.copyfile()을 호출해 작업을 수행합니다.
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            config_dir / f"{name}.yaml",
        )
    # yaml.safe_load()의 반환값을 settings_doc에 대입합니다.
    settings_doc = yaml.safe_load((config_dir / "settings.yaml").read_text(encoding="utf-8"))
    # 오른쪽 식을 계산한 값을 data_root에 대입합니다.
    data_root = tmp_path / "data"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    data_root.mkdir(parents=True)
    # str()의 반환값을 settings_doc['paths']['data_root']에 대입합니다.
    settings_doc["paths"]["data_root"] = str(data_root)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    (config_dir / "settings.yaml").write_text(
        yaml.safe_dump(settings_doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    # load_settings()의 반환값을 settings에 대입합니다.
    settings = load_settings(config_dir / "settings.yaml")
    # load_policies()의 반환값을 policies에 대입합니다.
    policies = load_policies(
        config_dir / "tools.yaml",
        config_dir / "privacy.yaml",
        settings=settings,
    )
    # 오른쪽 식을 계산한 값을 docs_root에 대입합니다.
    docs_root = data_root / "docs"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    docs_root.mkdir(parents=True)

    # 1. Exact error code keyword document
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    (docs_root / "error_codes.txt").write_text(
        "자비스 시스템 에러코드 ERR_STARK_007: 아크 리액터 출력 과부하 및 냉각수 부족 발생.",
        encoding="utf-8",
    )
    # 2. Semantic food preferences document
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    (docs_root / "preferences.txt").write_text(
        "보스는 이탈리안 요리 중에서 특히 토마토 파스타와 화덕 피자를 아주 선호하십니다.",
        encoding="utf-8",
    )

    # 오른쪽 식을 계산한 값을 db에 대입합니다.
    db = data_root / "memory" / "jarvis.sqlite3"
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(db, created_at=NOW)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return DocumentIndexer(
        database_path=db,
        docs_root=docs_root,
        settings=settings.rag,
        document_policy=policies.privacy.api_transmission.documents,
        ids=SystemIdFactory(),
        semantic=SemanticMemory(db.with_name("semantic.sqlite3"), settings.rag.semantic,
                                embedder=FoodEmbedder()),
    )


class FoodEmbedder:
    identity = "test-food:1"

    def embed(self, text: str) -> list[float]:
        if any(word in text for word in ("요리", "파스타", "스파게티")):
            return [1.0, 0.0]
        return [0.0, 1.0]


# pytest가 test_hybrid_rrf_search_exact_and_semantic()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: hybrid_indexer.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_hybrid_rrf_search_exact_and_semantic(hybrid_indexer: DocumentIndexer) -> None:
    # 1. Sync documents
    # hybrid_indexer.sync()의 반환값을 report에 대입합니다.
    report = hybrid_indexer.sync()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert report.indexed == 2

    # 2. Exact Keyword Query (FTS5 + RRF)
    # hybrid_indexer.search()의 반환값을 exact_hits에 대입합니다.
    exact_hits = hybrid_indexer.search("ERR_STARK_007 리액터")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(exact_hits) >= 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "ERR_STARK_007" in exact_hits[0].text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert exact_hits[0].relative_path == "error_codes.txt"

    # 3. Semantic / Synonym Query (512D Vector + RRF)
    # hybrid_indexer.search()의 반환값을 semantic_hits에 대입합니다.
    semantic_hits = hybrid_indexer.search("보스가 좋아하는 이태리 스파게티 요리")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(semantic_hits) >= 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "토마토 파스타" in semantic_hits[0].text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert semantic_hits[0].relative_path == "preferences.txt"

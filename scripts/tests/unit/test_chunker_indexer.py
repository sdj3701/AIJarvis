# 파이썬 공부 | scripts/tests/unit/test_chunker_indexer.py
# chunker_indexer 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Tests for document chunking and indexing."""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from app.config.loader import load_policies, load_settings
from app.core.ids import SystemIdFactory
from app.memory.migrations import initialize_database
from app.rag.chunker import chunk_text
from app.rag.indexer import DocumentIndexer

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase3
# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 14, 0, tzinfo=KST)


# indexer(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: DocumentIndexer.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def indexer(tmp_path: Path) -> DocumentIndexer:
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
    # shutil.copytree()을 호출해 작업을 수행합니다.
    shutil.copytree(
        REPOSITORY_ROOT / "scripts" / "tests" / "data" / "docs", docs_root, dirs_exist_ok=True
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
    )


# pytest가 test_chunk_overlap_produces_ordinals()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_chunk_overlap_produces_ordinals() -> None:
    # 오른쪽 식을 계산한 값을 text에 대입합니다.
    text = "가" * 2500
    # chunk_text()의 반환값을 chunks에 대입합니다.
    chunks = chunk_text(text, chunk_chars=1200, overlap_chars=150)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(chunks) >= 2
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert chunks[0].ordinal == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert chunks[1].start_char == 1050


# pytest가 test_index_and_search_public_doc()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: indexer.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_index_and_search_public_doc(indexer: DocumentIndexer) -> None:
    # indexer.sync()의 반환값을 report에 대입합니다.
    report = indexer.sync(now=NOW)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert report.indexed + report.updated >= 1
    # indexer.search()의 반환값을 hits에 대입합니다.
    hits = indexer.search("Jarvis")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert hits
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any("guide.md" in hit.relative_path for hit in hits)


# pytest가 test_reindex_same_file_does_not_duplicate_chunks()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: indexer.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_reindex_same_file_does_not_duplicate_chunks(indexer: DocumentIndexer) -> None:
    # indexer.sync()을 호출해 작업을 수행합니다.
    indexer.sync(now=NOW)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with closing(sqlite3.connect(indexer.database_path)) as connection:
        # 오른쪽 식을 계산한 값을 first에 대입합니다.
        first = connection.execute("SELECT count(*) FROM doc_chunks").fetchone()[0]
    # indexer.sync()을 호출해 작업을 수행합니다.
    indexer.sync(now=NOW)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with closing(sqlite3.connect(indexer.database_path)) as connection:
        # 오른쪽 식을 계산한 값을 second에 대입합니다.
        second = connection.execute("SELECT count(*) FROM doc_chunks").fetchone()[0]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first == second


# pytest가 test_deleted_document_removed_from_fts()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: indexer.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_deleted_document_removed_from_fts(indexer: DocumentIndexer) -> None:
    # indexer.sync()을 호출해 작업을 수행합니다.
    indexer.sync(now=NOW)
    # 오른쪽 식을 계산한 값을 private에 대입합니다.
    private = indexer.docs_root / "private" / "secret_notes.txt"
    # 지정한 파일 또는 링크를 삭제합니다.
    private.unlink()
    # indexer.sync()을 호출해 작업을 수행합니다.
    indexer.sync(now=NOW)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with closing(sqlite3.connect(indexer.database_path)) as connection:
        # 오른쪽 식을 계산한 값을 count에 대입합니다.
        count = connection.execute(
            "SELECT count(*) FROM doc_chunks_fts WHERE doc_chunks_fts MATCH 'secret'"
        ).fetchone()[0]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert count == 0


# pytest가 test_pdf_rejected_with_clear_message()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: indexer, tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_pdf_rejected_with_clear_message(indexer: DocumentIndexer, tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 pdf_path에 대입합니다.
    pdf_path = indexer.docs_root / "sample.pdf"
    # 바이트 데이터를 파일에 기록합니다.
    pdf_path.write_bytes(b"%PDF-1.4")
    # indexer.sync()의 반환값을 report에 대입합니다.
    report = indexer.sync(now=NOW)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert report.errors
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any("PDF" in item for item in report.errors)

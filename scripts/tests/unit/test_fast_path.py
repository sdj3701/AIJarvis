"""Unit and integration tests for FactFastPath and fast-path orchestration."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from app.llm.base import LLMResponse, LLMUsage, Message
from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.memory.store import SQLiteSessionStore
from app.orchestrator.fast_path import FactFastPath, FastPathMatch, normalize_query
from app.orchestrator.loop import ChatOrchestrator
from app.wiring import Runtime, build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
KST = timezone(timedelta(hours=9), name="KST")
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


def test_normalize_query():
    assert normalize_query("대한민국 수도는???") == "대한민국 수도는"
    assert normalize_query("  한국의 수도는 어디야!  ") == "한국의 수도는 어디야"


def test_fact_fast_path_default_matches():
    fp = FactFastPath()

    # 수도 질의
    m1 = fp.try_match("대한민국 수도는?")
    assert m1 is not None
    assert "서울" in m1.text
    assert m1.fact_key == "fact.capital_of_korea"

    m2 = fp.try_match("한국의 수도는 어디야")
    assert m2 is not None
    assert "서울" in m2.text

    m3 = fp.try_match("우리나라 수도")
    assert m3 is not None
    assert "서울" in m3.text

    # 이름 질의
    m4 = fp.try_match("너 이름이 뭐야?")
    assert m4 is not None
    assert "자비스" in m4.text

    # OS 질의
    m5 = fp.try_match("현재 os가 뭐야")
    assert m5 is not None
    assert "Windows PC" in m5.text

    # 역할 질의
    m6 = fp.try_match("너 역할이 뭐야")
    assert m6 is not None
    assert "개인 AI 비서" in m6.text


def test_fact_fast_path_bypasses_non_facts():
    fp = FactFastPath()

    # 도구/명령어 형태는 None 반환
    assert fp.try_match("/open_app discord") is None
    assert fp.try_match("디스코드 실행해줘") is None
    assert fp.try_match("새 파일 만들어") is None
    assert fp.try_match("최신 뉴스 검색해줘") is None

    # 복잡한 설명이나 비교 요청은 None 반환
    assert fp.try_match("대한민국 수도와 프랑스 수도를 비교해줘") is None
    assert fp.try_match("왜 서울이 수도가 되었는지 설명해줘") is None


def test_fact_fast_path_db_lookup():
    mock_sessions = MagicMock()
    mock_conn = MagicMock()
    mock_sessions._connection.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchone.return_value = ("특별수도",)

    fp = FactFastPath(mock_sessions)
    res = fp.try_match("대한민국 수도는?")
    assert res is not None
    assert res.fact_value == "특별수도"
    assert "특별수도" in res.text


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    destination = tmp_path / "config"
    destination.mkdir()
    for name in ("settings", "tools", "privacy"):
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            destination / f"{name}.yaml",
        )
    root = tmp_path / "Jarvis"
    create_tree(root)
    settings_path = destination / "settings.yaml"
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    document["paths"]["data_root"] = str(root)
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return destination


def test_orchestrator_fast_path_end_to_end(config_dir: Path):
    fake_llm = FakeLLMClient().reply("LLM에서 생성된 일반 답변입니다.")
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=fake_llm)
    initialize_database(runtime.memory_db, created_at=NOW)

    chat = ChatOrchestrator(
        settings=runtime.config.settings,
        llm=runtime.llm,
        sessions=runtime.sessions,
        budget=runtime.budget,
        masker=runtime.masker,
        events=runtime.events,
        clock=runtime.clock,
        sleeper=runtime.sleeper,
        random=runtime.random,
        ids=runtime.ids,
        metrics=runtime.metrics,
        summarizer=runtime.summarizer,
    )

    # 1. Fast-Path 질문 ("대한민국 수도는?")
    outcome = chat.handle_turn("대한민국 수도는?")
    assert outcome.ok is True
    assert "서울" in outcome.text
    # LLM이 호출되지 않았으므로 토큰 사용량 0
    assert outcome.input_tokens == 0
    assert outcome.output_tokens == 0
    assert outcome.cost_usd == Decimal("0")
    # Fake LLM 호출 횟수 0건이어야 함!
    assert len(fake_llm.calls) == 0

    # 2. 일반 질문 ("오늘 날씨 어때?") -> LLM으로 넘어가야 함
    outcome_normal = chat.handle_turn("오늘 날씨 어때?")
    assert outcome_normal.ok is True
    assert outcome_normal.text == "LLM에서 생성된 일반 답변입니다."
    # Fake LLM 호출 횟수 1건으로 증가!
    assert len(fake_llm.calls) == 1

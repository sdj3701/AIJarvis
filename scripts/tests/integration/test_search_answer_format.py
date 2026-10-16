# 파이썬 공부 | scripts/tests/integration/test_search_answer_format.py
# search_answer_format 관련 여러 기능의 연결을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Integration tests for research answers with FakeSearchProvider."""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.llm.base import LLMUsage
from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.rag.search_provider import SearchFailed
from app.tools.impl.web_search import WebSearchTool
from app.tools.registry import spec_from_definition
from app.wiring import Runtime, build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock
from tests.fakes.search import FakeSearchProvider

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase3
# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


# EVIDENCE_ANSWER에 문자열을 대입합니다.
EVIDENCE_ANSWER = """\
핵심 요약
- Jarvis는 로컬 문서를 검색합니다 [1]

근거
[1] Example — https://example.com/jarvis (2026-08-11 확인)

상태: 근거 부족
"""


# config_dir(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: Path.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    # 오른쪽 식을 계산한 값을 destination에 대입합니다.
    destination = tmp_path / "config"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    destination.mkdir()
    # for 반복문: 대상의 항목을 하나씩 name에 대입하며 아래 블록을 실행합니다.
    for name in ("settings", "tools", "privacy"):
        # shutil.copyfile()을 호출해 작업을 수행합니다.
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            destination / f"{name}.yaml",
        )
    # 오른쪽 식을 계산한 값을 root에 대입합니다.
    root = tmp_path / "Jarvis"
    # create_tree()을 호출해 작업을 수행합니다.
    create_tree(root)
    # 오른쪽 식을 계산한 값을 settings_path에 대입합니다.
    settings_path = destination / "settings.yaml"
    # yaml.safe_load()의 반환값을 document에 대입합니다.
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    # str()의 반환값을 document['paths']['data_root']에 대입합니다.
    document["paths"]["data_root"] = str(root)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return destination


# _research_runtime(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: config_dir, llm.
# 반환 타입 힌트: tuple[Runtime, ChatOrchestrator].
def _research_runtime(config_dir: Path, llm: FakeLLMClient) -> tuple[Runtime, ChatOrchestrator]:
    # build()의 반환값을 runtime에 대입합니다.
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=llm)
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(runtime.memory_db, created_at=NOW)
    # FakeSearchProvider()의 반환값을 fake에 대입합니다.
    fake = FakeSearchProvider()
    # fake.add_hit()을 호출해 작업을 수행합니다.
    fake.add_hit(
        title="Example",
        url="https://example.com/jarvis",
        snippet="Jarvis local docs",
        fetched_at=NOW,
    )
    # 오른쪽 식을 계산한 값을 enabled에 대입합니다.
    # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
    enabled = {
        defn.name: spec_from_definition(defn)
        for defn in runtime.config.policies.tools.tools
        if defn.enabled and defn.name in {"web_search", "doc_search"}
    }
    # WebSearchTool()의 반환값을 runtime.tool_runner.registry.tools['web_search']에 대입합니다.
    runtime.tool_runner.registry.tools["web_search"] = WebSearchTool(
        spec=enabled["web_search"],
        provider=fake,
        gate=runtime.privacy_gate,
        budget=runtime.budget,
        default_max_results=runtime.config.settings.rag.search.max_results,
        cost_per_request=runtime.config.settings.rag.search.cost_per_request,
    )
    # ChatOrchestrator()의 반환값을 chat에 대입합니다.
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
        indexer=runtime.indexer,
        research=runtime.research,
        tool_runner=runtime.tool_runner,
        safety_gate=runtime.safety_gate,
        approval_store=runtime.approval_store,
        audit_writer=runtime.audit_writer,
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return runtime, chat


# pytest가 test_unknown_fact_triggers_search_or_abstains()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_unknown_fact_triggers_search_or_abstains(config_dir: Path) -> None:
    # FakeLLMClient().reply()의 반환값을 llm에 대입합니다.
    llm = FakeLLMClient().reply(EVIDENCE_ANSWER, usage=LLMUsage(10, 20, Decimal("0"), 5))
    # 언패킹: 오른쪽 결과를 순서대로 (_, chat)에 나누어 담습니다.
    _, chat = _research_runtime(config_dir, llm)
    # chat.start()을 호출해 작업을 수행합니다.
    chat.start()
    # chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = chat.handle_turn("/search 웹 Jarvis 문서 검색")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.ok is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any("untrusted_content" in message.content for call in llm.calls for message in call)


# pytest가 test_answer_includes_url_and_status_label()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_answer_includes_url_and_status_label(config_dir: Path) -> None:
    # FakeLLMClient().reply()의 반환값을 llm에 대입합니다.
    llm = FakeLLMClient().reply(EVIDENCE_ANSWER)
    # 언패킹: 오른쪽 결과를 순서대로 (_, chat)에 나누어 담습니다.
    _, chat = _research_runtime(config_dir, llm)
    # chat.start()을 호출해 작업을 수행합니다.
    chat.start()
    # chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = chat.handle_turn("최신 Jarvis 검색해")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert re.search(r"https?://", outcome.text)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert re.search(r"상태\s*[:\uff1a]\s*(확실|상충|근거 부족)", outcome.text)


# pytest가 test_duplicate_url_does_not_count_as_independent_source()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_duplicate_url_does_not_count_as_independent_source(config_dir: Path) -> None:
    # FakeLLMClient().reply()의 반환값을 llm에 대입합니다.
    llm = FakeLLMClient().reply("핵심 요약\n- 중복 결과 [1]\n\n상태: 확실")
    # 언패킹: 오른쪽 결과를 순서대로 (runtime, chat)에 나누어 담습니다.
    runtime, chat = _research_runtime(config_dir, llm)
    # 오른쪽 식을 계산한 값을 web_tool에 대입합니다.
    web_tool = runtime.tool_runner.registry.tools["web_search"]
    # web_tool.provider.add_hit()을 호출해 작업을 수행합니다.
    web_tool.provider.add_hit(  # type: ignore[attr-defined]
        title="Duplicate",
        url="https://example.com/jarvis#duplicate",
        snippet="같은 출처의 다른 검색 결과",
        fetched_at=NOW,
    )
    # chat.start()을 호출해 작업을 수행합니다.
    chat.start()

    # chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = chat.handle_turn("최신 Jarvis 검색해")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "상태: 근거 부족" in outcome.text


# pytest가 test_search_failure_is_reported_honestly()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_search_failure_is_reported_honestly(config_dir: Path) -> None:
    # FakeLLMClient().reply()의 반환값을 llm에 대입합니다.
    llm = FakeLLMClient().reply("should not be used")
    # 언패킹: 오른쪽 결과를 순서대로 (runtime, chat)에 나누어 담습니다.
    runtime, chat = _research_runtime(config_dir, llm)
    # 오른쪽 식을 계산한 값을 enabled에 대입합니다.
    # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
    enabled = {
        defn.name: spec_from_definition(defn)
        for defn in runtime.config.policies.tools.tools
        if defn.enabled and defn.name == "web_search"
    }
    # FakeSearchProvider()의 반환값을 failing에 대입합니다.
    failing = FakeSearchProvider(fail_with=SearchFailed("검색 API 오류"))
    # WebSearchTool()의 반환값을 runtime.tool_runner.registry.tools['web_search']에 대입합니다.
    runtime.tool_runner.registry.tools["web_search"] = WebSearchTool(
        spec=enabled["web_search"],
        provider=failing,
        gate=runtime.privacy_gate,
        budget=runtime.budget,
        default_max_results=5,
        cost_per_request=Decimal("0"),
    )
    # chat.start()을 호출해 작업을 수행합니다.
    chat.start()
    # chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = chat.handle_turn("/search 웹 broken")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.ok is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "검색" in outcome.text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert llm.calls == []


# pytest가 test_local_doc_answer_cites_filename()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir, tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_local_doc_answer_cites_filename(config_dir: Path, tmp_path: Path) -> None:
    # FakeLLMClient().reply()의 반환값을 llm에 대입합니다.
    llm = FakeLLMClient().reply(
        "핵심 요약\n- 로컬 문서 [1]\n\n근거\n"
        "[1] guide.md — docs (2026-08-11 확인)\n\n상태: 근거 부족"
    )
    # 언패킹: 오른쪽 결과를 순서대로 (runtime, chat)에 나누어 담습니다.
    runtime, chat = _research_runtime(config_dir, llm)
    # 오른쪽 식을 계산한 값을 docs에 대입합니다.
    docs = runtime.config.settings.paths.data_root / "docs" / "public"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    docs.mkdir(parents=True, exist_ok=True)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    (docs / "guide.md").write_text("Jarvis memory structure 설명", encoding="utf-8")
    # runtime.indexer.sync()을 호출해 작업을 수행합니다.
    runtime.indexer.sync(now=NOW)
    # chat.start()을 호출해 작업을 수행합니다.
    chat.start()
    # chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = chat.handle_turn("로컬 문서에서 memory structure 찾아줘")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "guide.md" in outcome.text or "guide.md" in llm.calls[-1][1].content

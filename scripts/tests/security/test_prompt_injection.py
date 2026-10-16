# 파이썬 공부 | scripts/tests/security/test_prompt_injection.py
# prompt_injection 관련 보안 경계을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Security tests for prompt injection corpus."""

from __future__ import annotations

import json
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
from app.tools.impl.web_search import WebSearchTool
from app.tools.registry import spec_from_definition
from app.wiring import build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock
from tests.fakes.search import FakeSearchProvider

# pytestmark에 리스트(순서가 있고 수정 가능)을 대입합니다.
pytestmark = [pytest.mark.phase3, pytest.mark.security]
# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


# _load_cases(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: list[dict[str, str]].
def _load_cases() -> list[dict[str, str]]:
    # 오른쪽 식을 계산한 값을 path에 대입합니다.
    path = REPOSITORY_ROOT / "scripts" / "tests" / "data" / "malicious" / "injection.jsonl"
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# chat(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: tuple[FakeLLMClient, ChatOrchestrator].
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def chat(tmp_path: Path) -> tuple[FakeLLMClient, ChatOrchestrator]:
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
    # 오른쪽 식을 계산한 값을 root에 대입합니다.
    root = tmp_path / "Jarvis"
    # create_tree()을 호출해 작업을 수행합니다.
    create_tree(root)
    # 오른쪽 식을 계산한 값을 settings_path에 대입합니다.
    settings_path = config_dir / "settings.yaml"
    # yaml.safe_load()의 반환값을 document에 대입합니다.
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    # str()의 반환값을 document['paths']['data_root']에 대입합니다.
    document["paths"]["data_root"] = str(root)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    # FakeLLMClient().reply()의 반환값을 llm에 대입합니다.
    llm = FakeLLMClient().reply(
        "핵심 요약\n- 요약 [1]\n\n근거\n[1] evil.md — local (2026-08-11 확인)\n\n상태: 근거 부족",
        usage=LLMUsage(1, 1, Decimal("0"), 1),
    )
    # build()의 반환값을 runtime에 대입합니다.
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=llm)
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(runtime.memory_db, created_at=NOW)
    # FakeSearchProvider()의 반환값을 fake에 대입합니다.
    fake = FakeSearchProvider()
    # fake.add_hit()을 호출해 작업을 수행합니다.
    fake.add_hit(title="t", url="https://example.com", snippet="s", fetched_at=NOW)
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
        default_max_results=5,
        cost_per_request=Decimal("0"),
    )
    # ChatOrchestrator()의 반환값을 orchestrator에 대입합니다.
    orchestrator = ChatOrchestrator(
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
        indexer=runtime.indexer,
        research=runtime.research,
        tool_runner=runtime.tool_runner,
        safety_gate=runtime.safety_gate,
        approval_store=runtime.approval_store,
        audit_writer=runtime.audit_writer,
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return llm, orchestrator


# pytest가 test_injection_corpus()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: chat, case.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("case", _load_cases(), ids=lambda item: item["id"])
def test_injection_corpus(
    chat: tuple[FakeLLMClient, ChatOrchestrator],
    case: dict[str, str],
) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (llm, orchestrator)에 나누어 담습니다.
    llm, orchestrator = chat
    # 오른쪽 식을 계산한 값을 docs에 대입합니다.
    docs = orchestrator._indexer.docs_root / "evil.md"
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    docs.write_text("evil " + case["text"], encoding="utf-8")
    # orchestrator._indexer.sync()을 호출해 작업을 수행합니다.
    orchestrator._indexer.sync(now=NOW)
    # orchestrator.start()을 호출해 작업을 수행합니다.
    orchestrator.start()
    # orchestrator.handle_turn()을 호출해 작업을 수행합니다.
    orchestrator.handle_turn("/search evil")
    # '\n'.join()의 반환값을 sent에 대입합니다.
    sent = "\n".join(message.content for call in llm.calls for message in call)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "untrusted_content" in sent
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "create_file" not in sent.lower() or "데이터" in sent

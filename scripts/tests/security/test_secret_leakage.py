# 파이썬 공부 | scripts/tests/security/test_secret_leakage.py
# secret_leakage 관련 보안 경계을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Security tests for secret leakage and local_only documents."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.wiring import build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock
from tests.fakes.search import FakeSearchProvider

# pytestmark에 리스트(순서가 있고 수정 가능)을 대입합니다.
pytestmark = [pytest.mark.phase3, pytest.mark.phase6, pytest.mark.security]
# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)
# SECRET에 문자열을 대입합니다.
SECRET = "sk-testAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


# pytest가 test_local_only_doc_not_sent_to_api()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_local_only_doc_not_sent_to_api(tmp_path: Path) -> None:
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
        "핵심 요약\n- 로컬 전용 [1]\n\n근거\n"
        "[1] private.txt — local (2026-08-11 확인)\n\n상태: 근거 부족"
    )
    # build()의 반환값을 runtime에 대입합니다.
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=llm)
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(runtime.memory_db, created_at=NOW)
    # FakeSearchProvider()의 반환값을 search에 대입합니다.
    search = FakeSearchProvider()
    # runtime.tool_runner.registry.tools.get()의 반환값을 web_tool에 대입합니다.
    web_tool = runtime.tool_runner.registry.tools.get("web_search")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: web_tool is not None.
    if web_tool is not None:
        # 오른쪽 식을 계산한 값을 web_tool.provider에 대입합니다.
        web_tool.provider = search  # type: ignore[attr-defined]
    # 오른쪽 식을 계산한 값을 private에 대입합니다.
    private = runtime.indexer.docs_root / "private"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    private.mkdir(parents=True, exist_ok=True)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    (private / "secret.txt").write_text(f"secret marker {SECRET}", encoding="utf-8")
    # runtime.indexer.sync()을 호출해 작업을 수행합니다.
    runtime.indexer.sync(now=NOW)
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
        indexer=runtime.indexer,
        research=runtime.research,
        tool_runner=runtime.tool_runner,
        safety_gate=runtime.safety_gate,
        approval_store=runtime.approval_store,
        audit_writer=runtime.audit_writer,
    )
    # chat.start()을 호출해 작업을 수행합니다.
    chat.start()
    # chat.handle_turn()을 호출해 작업을 수행합니다.
    chat.handle_turn("/search secret")
    # '\n'.join()의 반환값을 sent에 대입합니다.
    sent = "\n".join(message.content for call in llm.calls for message in call)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert SECRET not in sent
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "로컬 전용" in sent


# pytest가 test_external_search_query_blocks_secret()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_external_search_query_blocks_secret(tmp_path: Path) -> None:
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
    # build()의 반환값을 runtime에 대입합니다.
    runtime = build(config_dir, clock=FrozenClock(NOW))
    # runtime.privacy_gate.for_external_text()의 반환값을 decision에 대입합니다.
    decision = runtime.privacy_gate.for_external_text(
        f"query with {SECRET}",
        purpose="search_query",
    )
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert decision.text is None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert decision.blocked is True


# pytest가 test_backup_manifest_contains_no_secrets()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_backup_manifest_contains_no_secrets(tmp_path: Path) -> None:
    from scripts.backup import create_backup, restore_backup

    # 오른쪽 식을 계산한 값을 data_root에 대입합니다.
    data_root = tmp_path / "data_root"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    (data_root / "memory" / "raw").mkdir(parents=True, exist_ok=True)
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    (data_root / "config").mkdir(parents=True, exist_ok=True)

    # Config has secret masked or dummy, raw log has secret token masked
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    (data_root / "config" / "settings.yaml").write_text("app:\n  language: ko\n", encoding="utf-8")
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    (data_root / "memory" / "raw" / "log.jsonl").write_text(
        json.dumps({"msg": f"Bearer [REDACTED:{SECRET[:4]}...]"}) + "\n",
        encoding="utf-8",
    )

    # 오른쪽 식을 계산한 값을 target_backup에 대입합니다.
    target_backup = tmp_path / "backups"
    # create_backup()의 반환값을 archive에 대입합니다.
    archive = create_backup(data_root, target_backup, password="test_secret_pw")

    # Restore to check manifest
    # 오른쪽 식을 계산한 값을 restore_target에 대입합니다.
    restore_target = tmp_path / "restored"
    # restore_backup()을 호출해 작업을 수행합니다.
    restore_backup(archive, restore_target, password="test_secret_pw", verify_retrieval=False)

    # (restore_target / 'manifest.json').read_text()의 반환값을 manifest_text에 대입합니다.
    manifest_text = (restore_target / "manifest.json").read_text(encoding="utf-8")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert SECRET not in manifest_text

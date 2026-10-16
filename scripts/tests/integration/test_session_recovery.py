# 파이썬 공부 | scripts/tests/integration/test_session_recovery.py
# session_recovery 관련 여러 기능의 연결을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Phase 2 integration tests for unfinished session recovery."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.memory.store import RawRecord
from app.orchestrator.recovery import recover_sessions
from app.wiring import build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase2
# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


# RecordingEvents: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class RecordingEvents:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # self.items에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.items: list[tuple[str, dict[str, Any]]] = []

    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.items.append((event_type, dict(payload)))


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
        # 오른쪽 식을 계산한 값을 source에 대입합니다.
        source = REPOSITORY_ROOT / "config" / f"{name}.example.yaml"
        # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
        (destination / f"{name}.yaml").write_text(
            source.read_text(encoding="utf-8"),
            encoding="utf-8",
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


# _unfinished_runtime(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: config_dir, recovery.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: tuple[Any, str].
def _unfinished_runtime(config_dir: Path, *, recovery: str) -> tuple[Any, str]:
    # build()의 반환값을 runtime에 대입합니다.
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=FakeLLMClient())
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(runtime.memory_db, created_at=NOW)
    # 오른쪽 식을 계산한 값을 settings_path에 대입합니다.
    settings_path = config_dir / "settings.yaml"
    # yaml.safe_load()의 반환값을 document에 대입합니다.
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    # 오른쪽 식을 계산한 값을 document['session']['recovery']에 대입합니다.
    document["session"]["recovery"] = recovery
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    # build()의 반환값을 runtime에 대입합니다.
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=FakeLLMClient())
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(runtime.memory_db, created_at=NOW)
    # runtime.ids.new()의 반환값을 session_id에 대입합니다.
    session_id = runtime.ids.new("ses")
    # runtime.sessions.start_session()을 호출해 작업을 수행합니다.
    runtime.sessions.start_session(session_id, NOW)
    # runtime.sessions.append_raw()을 호출해 작업을 수행합니다.
    runtime.sessions.append_raw(
        RawRecord(
            ts=NOW,
            session_id=session_id,
            turn_id=runtime.ids.new("turn"),
            role="user",
            content="미완료 세션",
            channel="text",
            request_id=runtime.ids.new("req"),
        )
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return runtime, session_id


# pytest가 test_discard_policy_ends_unfinished_session()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_discard_policy_ends_unfinished_session(config_dir: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (runtime, session_id)에 나누어 담습니다.
    runtime, session_id = _unfinished_runtime(config_dir, recovery="discard")
    # RecordingEvents()의 반환값을 events에 대입합니다.
    events = RecordingEvents()

    # recover_sessions()의 반환값을 report에 대입합니다.
    report = recover_sessions(
        runtime.sessions,
        policy="discard",
        events=events,
        clock=runtime.clock,
    )

    # runtime.sessions.get_session()의 반환값을 session에 대입합니다.
    session = runtime.sessions.get_session(session_id)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert session is not None and session.end_reason == "discarded"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert report.unfinished_count == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any(item[1].get("action") == "discarded" for item in events.items)


# pytest가 test_auto_policy_summarizes_unfinished_session()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_auto_policy_summarizes_unfinished_session(config_dir: Path) -> None:
    # 언패킹: 오른쪽 결과를 순서대로 (runtime, session_id)에 나누어 담습니다.
    runtime, session_id = _unfinished_runtime(config_dir, recovery="auto")
    # json.dumps()의 반환값을 summary_json에 대입합니다.
    summary_json = json.dumps(
        {
            "schema_version": 1,
            "summary": "크래시 복구 요약",
            "fact_candidates": [],
            "corrections": [],
            "tags": [],
        },
        ensure_ascii=False,
    )
    # runtime.llm.reply()을 호출해 작업을 수행합니다.
    runtime.llm.reply(summary_json)
    # RecordingEvents()의 반환값을 events에 대입합니다.
    events = RecordingEvents()

    # recover_sessions()을 호출해 작업을 수행합니다.
    recover_sessions(
        runtime.sessions,
        policy="auto",
        events=events,
        clock=runtime.clock,
        summarizer=runtime.summarizer,
        settings=runtime.config.settings,
        ids=runtime.ids,
        sleeper=runtime.sleeper,
        random=runtime.random,
    )

    # runtime.sessions.get_session()의 반환값을 session에 대입합니다.
    session = runtime.sessions.get_session(session_id)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert session is not None and session.end_reason == "crash_recovered"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert runtime.sessions.list_records(kind="summary")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any(item[1].get("action") in {"summarized", "recovered"} for item in events.items)

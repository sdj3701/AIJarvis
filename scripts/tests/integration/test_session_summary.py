# 파이썬 공부 | scripts/tests/integration/test_session_summary.py
# session_summary 관련 여러 기능의 연결을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Integration tests for session-end summarization."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import pytest

from app.cli import run_cli
from app.llm.fake import FakeLLMClient
from app.orchestrator.loop import ChatOrchestrator
from tests.integration.test_chat_turn import EventingFakeLLM, _chat, _runtime

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase2
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)
# TURN_ID에 문자열을 대입합니다.
TURN_ID = "turn_01KZQ6CQWDC6W068WDYMT2ZY4C"


# _summary_json(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: turn_id.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 문자열(str).
def _summary_json(*, turn_id: str = TURN_ID) -> str:
    # payload에 딕셔너리(키와 값의 쌍)을 대입합니다.
    payload = {
        "schema_version": 1,
        "summary": "사용자가 답변 말투를 짧게 바꾸길 원함",
        "fact_candidates": [
            {
                "key": "pref.answer_style",
                "value": "짧고 근거 포함",
                "confidence": 0.8,
                "evidence_turn_ids": [turn_id],
            }
        ],
        "corrections": [],
        "tags": ["preference"],
    }
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return json.dumps(payload, ensure_ascii=False)


# pytest가 test_bye_creates_summary_and_candidates()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_bye_creates_summary_and_candidates(config_dir: Path) -> None:
    # EventingFakeLLM().reply()의 반환값을 llm에 대입합니다.
    llm = EventingFakeLLM().reply("알겠습니다")
    # _runtime()의 반환값을 runtime에 대입합니다.
    runtime = _runtime(config_dir, llm)
    # _chat()의 반환값을 chat에 대입합니다.
    chat = _chat(runtime, summarizer=runtime.summarizer)
    # chat.start()을 호출해 작업을 수행합니다.
    chat.start()
    # chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = chat.handle_turn("앞으로 말투는 짧게")
    # llm.reply()을 호출해 작업을 수행합니다.
    llm.reply(_summary_json(turn_id=outcome.turn_id))
    # chat.end()을 호출해 작업을 수행합니다.
    chat.end(reason="bye")

    # runtime.sessions.list_records()의 반환값을 summaries에 대입합니다.
    summaries = runtime.sessions.list_records(kind="summary", status="confirmed")
    # runtime.sessions.list_records()의 반환값을 candidates에 대입합니다.
    candidates = runtime.sessions.list_records(status="candidate")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(summaries) == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(candidates) == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert candidates[0].key == "pref.answer_style"


# pytest가 test_cli_bye_runs_summarizer()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_cli_bye_runs_summarizer(config_dir: Path) -> None:
    # FakeLLMClient().reply('네').reply()의 반환값을 llm에 대입합니다.
    llm = FakeLLMClient().reply("네").reply(_summary_json())
    # _runtime()의 반환값을 runtime에 대입합니다.
    runtime = _runtime(config_dir, llm)
    runtime.config.settings.memory.summarize_on_exit  # noqa: B018
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
        summarizer=runtime.summarizer,
    )
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()
    # run_cli()의 반환값을 exit_code에 대입합니다.
    exit_code = run_cli(
        input_stream=StringIO("안녕\n/bye\n"),
        output_stream=output,
        chat=chat,
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert exit_code == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert runtime.sessions.list_records(kind="summary")

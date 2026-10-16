# 파이썬 공부 | scripts/tests/integration/test_memory_across_sessions.py
# memory_across_sessions 관련 여러 기능의 연결을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Integration tests for memory persistence across sessions."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.memory.commands import try_handle_memory_command
from app.memory.models import MemoryQuery
from tests.integration.test_chat_turn import EventingFakeLLM, _chat, _runtime

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase2
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


# pytest가 test_preference_applied_after_restart()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_preference_applied_after_restart(config_dir: Path) -> None:
    # EventingFakeLLM().reply('기억했습니다').reply()의 반환값을 llm에 대입합니다.
    llm = EventingFakeLLM().reply("기억했습니다").reply("짧게 답변")
    # _runtime()의 반환값을 runtime에 대입합니다.
    runtime = _runtime(config_dir, llm)
    # _chat()의 반환값을 chat에 대입합니다.
    chat = _chat(runtime, summarizer=runtime.summarizer)
    # chat.start()을 호출해 작업을 수행합니다.
    chat.start()
    # chat.memory_command_context()의 반환값을 ctx에 대입합니다.
    ctx = chat.memory_command_context()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ctx is not None
    # try_handle_memory_command()의 반환값을 result에 대입합니다.
    result = try_handle_memory_command("기억해: 말투는 짧고 근거 포함", ctx)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result is not None and result.ok is True
    # chat.end()을 호출해 작업을 수행합니다.
    chat.end(reason="bye")

    # _chat()의 반환값을 chat2에 대입합니다.
    chat2 = _chat(runtime, summarizer=runtime.summarizer)
    # chat2.start()을 호출해 작업을 수행합니다.
    chat2.start()
    # chat2.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = chat2.handle_turn("내 말투 preference 알려줘")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.ok is True
    # runtime.sessions.search()의 반환값을 search에 대입합니다.
    search = runtime.sessions.search(MemoryQuery(text="말투", now=NOW))
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any(item.record.key == "pref.answer_style" for item in search.matches)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any(
        "confirmed_memory" in message.content
        for message in llm.calls[-1]
        if message.role == "system"
    )


# pytest가 test_memory_eval_hits_expectations()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_memory_eval_hits_expectations(config_dir: Path) -> None:
    # EventingFakeLLM()의 반환값을 llm에 대입합니다.
    llm = EventingFakeLLM()
    # _runtime()의 반환값을 runtime에 대입합니다.
    runtime = _runtime(config_dir, llm)
    # _chat()의 반환값을 chat에 대입합니다.
    chat = _chat(runtime)
    # chat.start()을 호출해 작업을 수행합니다.
    chat.start()
    # chat.memory_command_context()의 반환값을 ctx에 대입합니다.
    ctx = chat.memory_command_context()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ctx is not None
    # samples에 리스트(순서가 있고 수정 가능)을 대입합니다.
    samples = [
        ("기억해: 말투는 짧게", "pref.answer_style"),
        ("기억해: 언어는 한국어", "pref.language"),
        ("기억해: 노트 폴더는 D:\\notes", "env.notes_dir"),
    ]
    # for 반복문: 대상의 항목을 하나씩 (text, key)에 대입하며 아래 블록을 실행합니다.
    for text, key in samples:
        # try_handle_memory_command()의 반환값을 result에 대입합니다.
        result = try_handle_memory_command(text, ctx)
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert result is not None and result.ok is True
        # runtime.sessions.get_record()의 반환값을 stored에 대입합니다.
        stored = runtime.sessions.get_record(result.record_ids[0])
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert stored is not None and stored.key == key

    # 오른쪽 식을 계산한 값을 eval_path에 대입합니다.
    eval_path = Path(__file__).resolve().parents[1] / "data" / "memory_eval.jsonl"
    # 아래 함수()의 반환값을 lines에 대입합니다.
    lines = eval_path.read_text(encoding="utf-8").splitlines()
    # hits에 숫자 등 고정된 값을 대입합니다.
    hits = 0
    # total에 숫자 등 고정된 값을 대입합니다.
    total = 0
    # for 반복문: 대상의 항목을 하나씩 line에 대입하며 아래 블록을 실행합니다.
    for line in lines:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not line.strip().
        if not line.strip():
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        total += 1
        # json.loads()의 반환값을 item에 대입합니다.
        item = json.loads(line)
        # runtime.sessions.search()의 반환값을 result에 대입합니다.
        result = runtime.sessions.search(MemoryQuery(text=item["query"], now=NOW))
        # 오른쪽 식을 계산한 값을 found_keys에 대입합니다.
        # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
        found_keys = {scored.record.key for scored in result.matches if scored.record.key}
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다:
        # set(item['expect_keys']).issubset(found_keys).
        if set(item["expect_keys"]).issubset(found_keys):
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            hits += 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert total > 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert hits / total >= 0.9

# 파이썬 공부 | scripts/tests/integration/test_tool_execution.py
# tool_execution 관련 여러 기능의 연결을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Integration tests for secure tool execution."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from unittest.mock import patch

import pytest

from tests.helpers.phase4_app import Phase4App
from tests.security.test_approval_binding import _ctx

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase4


# pytest가 test_open_allowed_app()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_open_allowed_app(phase4_app: Phase4App) -> None:
    # phase4_app.chat.handle_turn()의 반환값을 pending에 대입합니다.
    pending = phase4_app.chat.handle_turn("/open_app notepad")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert pending.pending_approval is not None
    # phase4_app.runtime.approval_store.grant()의 반환값을 ticket에 대입합니다.
    ticket = phase4_app.runtime.approval_store.grant(
        pending.pending_approval, ctx=phase4_app.chat.pending_context, method="user_text",
    )
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.subprocess.Popen") as popen:
        # 오른쪽 식을 계산한 값을 proc에 대입합니다.
        proc = popen.return_value
        # proc.pid에 숫자 등 고정된 값을 대입합니다.
        proc.pid = 4242
        # phase4_app.chat.resume_after_approval()의 반환값을 outcome에 대입합니다.
        outcome = phase4_app.chat.resume_after_approval(ticket)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.ok
    # phase4_app.audit()의 반환값을 audit에 대입합니다.
    audit = phase4_app.audit()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any(record["phase"] == "intent" for record in audit)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any(record["phase"] == "result" for record in audit)


# pytest가 test_unlisted_app_denied_with_reason()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_unlisted_app_denied_with_reason(phase4_app: Phase4App) -> None:
    # phase4_app.chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = phase4_app.chat.handle_turn("/open_app chrome")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not outcome.ok
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert phase4_app.audit()[-1]["phase"] == "denied"


# pytest가 test_create_file_with_approval()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_create_file_with_approval(phase4_app: Phase4App) -> None:
    import uuid

    # 오른쪽 식을 계산한 값을 name에 대입합니다.
    # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
    name = f"hello-{uuid.uuid4().hex[:8]}.md"
    # phase4_app.chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = phase4_app.chat.handle_turn(f"/create_file notes {name} hello")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.pending_approval is not None
    # phase4_app.runtime.approval_store.grant()의 반환값을 ticket에 대입합니다.
    ticket = phase4_app.runtime.approval_store.grant(
        outcome.pending_approval,
        ctx=phase4_app.chat.pending_context,  # type: ignore[arg-type]
        method="user_text",
    )
    # phase4_app.chat.resume_after_approval()의 반환값을 resumed에 대입합니다.
    resumed = phase4_app.chat.resume_after_approval(ticket)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert resumed.ok
    # 오른쪽 식을 계산한 값을 target에 대입합니다.
    target = phase4_app.data_root / "docs" / "notes" / name
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert target.is_file()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert target.read_text(encoding="utf-8") == "hello"


# pytest가 test_create_file_content_is_masked_in_audit()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_create_file_content_is_masked_in_audit(phase4_app: Phase4App) -> None:
    # secret에 문자열을 대입합니다.
    secret = "sk-abcdefghijklmnopqrstuvwxyz"
    # phase4_app.chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = phase4_app.chat.handle_turn(
        f"/create_file notes audit-secret.md {secret}"
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.pending_approval is not None
    # json.dumps()의 반환값을 serialized에 대입합니다.
    serialized = json.dumps(phase4_app.audit(), ensure_ascii=False)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert secret not in serialized
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "OpenAI 형식 API 키" in serialized


# pytest가 test_allowlisted_app_is_detached()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_allowlisted_app_is_detached(phase4_app: Phase4App) -> None:
    # phase4_app.chat.handle_turn()의 반환값을 pending에 대입합니다.
    pending = phase4_app.chat.handle_turn("/open_app calc")
    # phase4_app.runtime.approval_store.grant()의 반환값을 ticket에 대입합니다.
    ticket = phase4_app.runtime.approval_store.grant(
        pending.pending_approval, ctx=phase4_app.chat.pending_context, method="user_text",
    )
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.subprocess.Popen") as popen:
        # popen.return_value.pid에 숫자 등 고정된 값을 대입합니다.
        popen.return_value.pid = 9999
        # phase4_app.chat.resume_after_approval()의 반환값을 outcome에 대입합니다.
        outcome = phase4_app.chat.resume_after_approval(ticket)
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert outcome.ok
        # popen.assert_called_once()을 호출해 작업을 수행합니다.
        popen.assert_called_once()
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert popen.call_args.kwargs.get("shell") is False


# pytest가 test_timeout_kills_process_tree()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
# 이 pytest 마커는 테스트 분류 또는 실행 조건을 지정합니다.
@pytest.mark.skipif(os.name != "nt", reason="Windows timeout process test")
def test_timeout_kills_process_tree(phase4_app: Phase4App) -> None:
    import sys
    import time

    from app.llm.base import ToolCall

    # 오른쪽 식을 계산한 값을 runner에 대입합니다.
    runner = phase4_app.runtime.tool_runner
    # 오른쪽 식을 계산한 값을 spec에 대입합니다.
    spec = runner.registry.specs["web_search"]
    # replace()의 반환값을 managed_spec에 대입합니다.
    managed_spec = replace(spec, execution_mode="managed_process", timeout_s=1)

    # SlowManaged: 관련 데이터와 동작을 한데 묶는 클래스입니다.
    class SlowManaged:
        # 오른쪽 식을 계산한 값을 spec에 대입합니다.
        spec = managed_spec

        # managed_command(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 입력: args, tctx.
        def managed_command(self, args, tctx):
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return [
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ]

        # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 입력: args, tctx.
        def run(self, args, tctx):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise AssertionError("managed_process only")

    # 오른쪽 식을 계산한 값을 runner.registry.specs['web_search']에 대입합니다.
    runner.registry.specs["web_search"] = managed_spec
    # SlowManaged()의 반환값을 runner.registry.tools['web_search']에 대입합니다.
    runner.registry.tools["web_search"] = SlowManaged()  # type: ignore[assignment]
    # ToolCall()의 반환값을 call에 대입합니다.
    call = ToolCall(id="slow", name="web_search", arguments={"query": "test"})
    # runner.execute()의 반환값을 result에 대입합니다.
    result = runner.execute(call, ctx=_ctx(phase4_app), ticket=None)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not result.ok
    # 지정한 시간만큼 현재 실행을 기다리게 합니다.
    time.sleep(0.3)

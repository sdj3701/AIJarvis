# 파이썬 공부 | scripts/app/orchestrator/envelope.py
# 외부 자료를 지시문과 구분할 수 있는 형태로 감쌉니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Untrusted content envelope helpers for LLM prompt injection mitigation."""

from __future__ import annotations

from datetime import datetime


# escape_untrusted_body(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text.
# 반환 타입 힌트: 문자열(str).
def escape_untrusted_body(text: str) -> str:
    """Escape envelope-like tags inside untrusted body text."""
    # text.replace()의 반환값을 escaped에 대입합니다.
    escaped = text.replace("</untrusted_content>", "&lt;/untrusted_content&gt;")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return escaped.replace("<untrusted_content", "&lt;untrusted_content")


# wrap_untrusted_content(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: source, source_kind, fetched_at, body, chunk.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 문자열(str).
def wrap_untrusted_content(
    *,
    source: str,
    source_kind: str,
    fetched_at: datetime,
    body: str,
    chunk: str | None = None,
    source_id: str | None = None,
) -> str:
    # 오른쪽 식을 계산한 값을 attrs에 대입합니다.
    # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
    attrs = (
        f'source="{_escape_attr(source)}" '
        f'source_kind="{_escape_attr(source_kind)}" '
        f'fetched_at="{fetched_at.isoformat(timespec="seconds")}" '
        'trust="none"'
    )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: chunk is not None.
    if source_id is not None:
        attrs += f' source_id="{_escape_attr(source_id)}"'
    if chunk is not None:
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        attrs += f' chunk="{_escape_attr(chunk)}"'
    # escape_untrusted_body()의 반환값을 safe_body에 대입합니다.
    safe_body = escape_untrusted_body(body)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
    return f"<untrusted_content {attrs}>\n{safe_body}\n</untrusted_content>"


# _escape_attr(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value.
# 반환 타입 힌트: 문자열(str).
def _escape_attr(value: str) -> str:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return value.replace('"', "&quot;")

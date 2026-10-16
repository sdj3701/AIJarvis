# 파이썬 공부 | scripts/app/voice/wake_match.py
# 인식된 문장에서 호출어를 구분하고 문장 앞의 호출어를 제거합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Pure wake-word matching helpers for false-wake reduction and inline commands."""

from __future__ import annotations

import re
from typing import Literal

# 오른쪽 식을 계산한 값을 WakeMatchKind에 대입합니다.
WakeMatchKind = Literal["none", "standalone", "prefix"]

# re.compile()의 반환값을 _NON_WORD에 대입합니다.
# 정규식의 [^...]는 대괄호에 적은 범위에 속하지 않는 문자를 찾습니다.
# 숫자·영문·한글 음절 외의 문자(예: 공백과 느낌표)를 제거하는 데 사용합니다.
_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣]")


# 공백·기호를 지우고 영문 대소문자를 통일하여 호출어를 비교하기 쉽게 만듭니다.
# 예: "자 비스!"는 "자비스"가 됩니다.
# 입력: text.
# 반환 타입 힌트: 문자열(str).
def normalize_spoken_command(text: str) -> str:
    # sub("", text)는 패턴과 맞는 문자를 빈 문자열로 바꿉니다.
    # 그 결과에 casefold()를 이어 호출해 영문 대소문자도 통일합니다.
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return _NON_WORD.sub("", text).casefold()


# 호출어가 없으면 none, 호출어만 있으면 standalone, 앞에 있으면 prefix입니다.
# 중간에 나온 호출어는 명령의 시작으로 취급하지 않습니다.
# 입력: text, wake_word.
# 반환 타입 힌트: WakeMatchKind.
def wake_match_kind(text: str, wake_word: str) -> WakeMatchKind:
    # normalize_spoken_command()의 반환값을 normalized에 대입합니다.
    normalized = normalize_spoken_command(text)
    # normalize_spoken_command()의 반환값을 wake에 대입합니다.
    wake = normalize_spoken_command(wake_word)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not normalized or not wake.
    if not normalized or not wake:
        # 'none'을 반환하고 이 함수의 실행을 끝냅니다.
        return "none"
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: normalized == wake.
    if normalized == wake:
        # 'standalone'을 반환하고 이 함수의 실행을 끝냅니다.
        return "standalone"
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: normalized.startswith(wake).
    if normalized.startswith(wake):
        # 'prefix'을 반환하고 이 함수의 실행을 끝냅니다.
        return "prefix"
    # 'none'을 반환하고 이 함수의 실행을 끝냅니다.
    return "none"


# 문장 앞의 호출어 하나를 제거합니다. 공백·구두점과 분리된 발음을 함께 다룹니다.
# 입력: text, wake_word.
# 반환 타입 힌트: 문자열(str).
def _strip_one_leading_wake(text: str, wake_word: str) -> str:
    # text.strip()의 반환값을 stripped에 대입합니다.
    stripped = text.strip()
    # wake_word.strip()의 반환값을 wake에 대입합니다.
    wake = wake_word.strip()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not stripped or not wake.
    if not stripped or not wake:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return stripped
    # wake_match_kind()의 반환값을 kind에 대입합니다.
    kind = wake_match_kind(stripped, wake)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: kind == 'none'.
    if kind == "none":
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return stripped
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: kind == 'standalone'.
    if kind == "standalone":
        # ''을 반환하고 이 함수의 실행을 끝냅니다.
        return ""
    # re.compile()의 반환값을 pattern에 대입합니다.
    pattern = re.compile(
        # ^는 문장 시작, \s는 공백, *는 0회 이상 반복입니다.
        # re.escape는 호출어 안의 특수문자가 정규식 명령으로 해석되지 않도록 합니다.
        rf"^[\s.,!?·]*{re.escape(wake)}(?:\s+|[\s.,!?·]+)",
        re.IGNORECASE,
    )
    # pattern.sub('', stripped, count=1).strip()의 반환값을 remainder에 대입합니다.
    remainder = pattern.sub("", stripped, count=1).strip()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: remainder.
    if remainder:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return remainder
    # normalize_spoken_command()의 반환값을 compact_wake에 대입합니다.
    compact_wake = normalize_spoken_command(wake)
    # stripped.split()의 반환값을 tokens에 대입합니다.
    tokens = stripped.split()
    # consumed에 문자열을 대입합니다.
    consumed = ""
    # index에 숫자 등 고정된 값을 대입합니다.
    index = 0
    # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
    while index < len(tokens) and normalize_spoken_command(consumed) != compact_wake:
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        consumed += tokens[index]
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        index += 1
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: normalize_spoken_command(consumed) ==
    # compact_wake.
    if normalize_spoken_command(consumed) == compact_wake:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return " ".join(tokens[index:]).strip()
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return stripped


# 문장 앞에 반복된 호출어를 최대 네 차례 제거하고 실제 질문을 남깁니다.
# 입력: text, wake_word.
# 반환 타입 힌트: 문자열(str).
def strip_leading_wake_word(text: str, wake_word: str) -> str:
    """Remove one or more leading wake words; empty when only wake remains."""
    # text.strip()의 반환값을 current에 대입합니다.
    current = text.strip()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not current.
    if not current:
        # ''을 반환하고 이 함수의 실행을 끝냅니다.
        return ""
    # Guard against "자비스 자비스 …" artifacts from wake grammar or prompt bias.
    # range(4)는 0, 1, 2, 3을 제공합니다. _는 회차의 숫자를 쓰지 않겠다는 관례입니다.
    # 무한히 제거하지 않도록 최대 네 번만 반복합니다.
    for _ in range(4):
        # wake_match_kind()의 반환값을 kind에 대입합니다.
        kind = wake_match_kind(current, wake_word)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: kind == 'none'.
        if kind == "none":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return current
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: kind == 'standalone'.
        if kind == "standalone":
            # ''을 반환하고 이 함수의 실행을 끝냅니다.
            return ""
        # _strip_one_leading_wake()의 반환값을 nxt에 대입합니다.
        nxt = _strip_one_leading_wake(current, wake_word)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: nxt == current.
        if nxt == current:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return current
        # 오른쪽 식을 계산한 값을 current에 대입합니다.
        current = nxt
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return current

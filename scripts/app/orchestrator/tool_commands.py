# 파이썬 공부 | scripts/app/orchestrator/tool_commands.py
# 슬래시 명령과 간단한 자연어에서 실행할 도구와 인자를 추출합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Parse CLI and simple natural-language tool intents."""

from __future__ import annotations

import re

from app.llm.base import ToolCall

# re.compile()의 반환값을 _OPEN_APP에 대입합니다.
_OPEN_APP = re.compile(r"^/open_app(?:\s+(?P<app>.+))?$", re.I)
# re.compile()의 반환값을 _OPEN에 대입합니다.
_OPEN = re.compile(r"^/open(?:\s+(?P<app>\S+))?$", re.I)
# re.compile()의 반환값을 _OPEN_FOLDER에 대입합니다.
_OPEN_FOLDER = re.compile(
    r"^/open_folder(?:\s+(?P<root>\S+)(?:\s+(?P<relative>.+))?)?$",
    re.I,
)
# re.compile()의 반환값을 _OPEN_URL에 대입합니다.
_OPEN_URL = re.compile(r"^/open_url(?:\s+(?P<url>\S+))?$", re.I)
# re.compile()의 반환값을 _CREATE_FILE에 대입합니다.
_CREATE_FILE = re.compile(
    r"^/create_file(?:\s+(?P<root>\S+)\s+(?P<relative>\S+)(?:\s+(?P<content>.+))?)?$",
    re.I,
)

# frozenset()의 반환값을 APPROVAL_WORDS에 대입합니다.
APPROVAL_WORDS = frozenset({
    "허용", "허용해", "허용해줘", "허용할게", "허락할게", "승인할게", "예", "네",
})


# parse_tool_command(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text.
# 반환 타입 힌트: ToolCall | None.
def parse_tool_command(text: str) -> ToolCall | None:
    # text.strip()의 반환값을 stripped에 대입합니다.
    stripped = text.strip()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not stripped.
    if not stripped:
        # None을 반환하고 이 함수의 실행을 끝냅니다.
        return None

    # re.fullmatch()의 반환값을 close에 대입합니다.
    close = re.fullmatch(r"/close_app\s+(\w+)(\s+--force)?", stripped, re.I)
    # re.fullmatch()의 반환값을 korean에 대입합니다.
    korean = re.fullmatch(
        r"(?:카카오톡|카톡|kakaotalk)(?:을|를)?\s*(강제\s*)?"
        r"(?:종료(?:해\s*줘|시켜\s*줘|시켜|해)?|꺼\s*줘|닫아\s*줘)[.!]?",
        stripped, re.I,
    )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: close or korean.
    if close or korean:
        # bool()의 반환값을 force에 대입합니다.
        force = bool(close.group(2) if close else korean and korean.group(1))
        # 오른쪽 식을 계산한 값을 app에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        app = close.group(1).lower() if close else "kakaotalk"
        # {'카톡': 'kakaotalk', '카카오톡': 'kakaotalk'}.get()의 반환값을 app에 대입합니다.
        app = {"카톡": "kakaotalk", "카카오톡": "kakaotalk"}.get(app, app)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ToolCall(
            id="explicit_close_force" if force else "explicit_close_normal",
            name="close_app", arguments={"app": app, "force": force},
        )

    # 오른쪽 식을 계산한 값을 match에 대입합니다.
    match = _OPEN_APP.match(stripped) or _OPEN.match(stripped)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match is not None.
    if match is not None:
        # (match.group('app') or '').strip().lower()의 반환값을 app에 대입합니다.
        app = (match.group("app") or "").strip().lower()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not app.
        if not app:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ToolCall(id="cli_open_app", name="open_app", arguments={"app": app})

    # _OPEN_FOLDER.match()의 반환값을 match에 대입합니다.
    match = _OPEN_FOLDER.match(stripped)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match is not None.
    if match is not None:
        # (match.group('root') or '').strip()의 반환값을 root에 대입합니다.
        root = (match.group("root") or "").strip()
        # (match.group('relative') or '.').strip()의 반환값을 relative에 대입합니다.
        relative = (match.group("relative") or ".").strip()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not root.
        if not root:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ToolCall(
            id="cli_open_folder",
            name="open_folder",
            arguments={"root": root, "relative_path": relative},
        )

    # _OPEN_URL.match()의 반환값을 match에 대입합니다.
    match = _OPEN_URL.match(stripped)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match is not None.
    if match is not None:
        # (match.group('url') or '').strip()의 반환값을 url에 대입합니다.
        url = (match.group("url") or "").strip()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not url.
        if not url:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ToolCall(id="cli_open_url", name="open_url", arguments={"url": url})

    # _CREATE_FILE.match()의 반환값을 match에 대입합니다.
    match = _CREATE_FILE.match(stripped)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match is not None.
    if match is not None:
        # (match.group('root') or '').strip()의 반환값을 root에 대입합니다.
        root = (match.group("root") or "").strip()
        # (match.group('relative') or '').strip()의 반환값을 relative에 대입합니다.
        relative = (match.group("relative") or "").strip()
        # 오른쪽 식을 계산한 값을 content에 대입합니다.
        content = match.group("content") or ""
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not root or not relative.
        if not root or not relative:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ToolCall(
            id="cli_create_file",
            name="create_file",
            arguments={"root": root, "relative_path": relative, "content": content},
        )

    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return parse_simple_korean_intent(stripped)


# parse_simple_korean_intent(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text.
# 반환 타입 힌트: ToolCall | None.
def parse_simple_korean_intent(text: str) -> ToolCall | None:
    # text.strip()의 반환값을 lowered에 대입합니다.
    lowered = text.strip()
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if any(word in lowered for word in ("검색", "찾아", "폴더", "저장", "파일", "링크", "사이트")):
        # None을 반환하고 이 함수의 실행을 끝냅니다.
        return None
    # re.fullmatch()의 반환값을 match에 대입합니다.
    match = re.fullmatch(
        # Match the complete verb before its suffix (시켜줘 contains 켜줘).
        # Support 시행시켜줘, observed in the user's STT failure log.
        r"([\w .+\-]+?)(?:을|를)?\s*"
        r"(?:실행(?:\s*(?:해|시켜)(?:\s*줘)?)?|시행\s*(?:해|시켜)\s*줘|켜\s*줘|열어\s*줘)"
        r"(?:[.!]?\s+(?:허락할게|허용할게|승인할게)|[.!](?:허락할게|허용할게|승인할게))?"
        r"[.!]?", lowered
    )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match.
    if match:
        # Inline consent expresses intent only: the gate must still identify the
        # executable and ask for a target-bound ticket before saving permission.
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ToolCall("nl_open_app", "open_app", {"app": match.group(1).strip()})
    # None을 반환하고 이 함수의 실행을 끝냅니다.
    return None

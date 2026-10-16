# 파이썬 공부 | scripts/app/orchestrator/response_presenter.py
# 추가 AI 요청 없이 답변의 표시 형식을 정리합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""One-sentence presentation without an extra model request or semantic truncation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.orchestrator.rulebook import Rulebook

# 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: TYPE_CHECKING.
if TYPE_CHECKING:
    from app.orchestrator.loop import TurnOutcome

# FALLBACK에 문자열을 대입합니다.
FALLBACK = "답변이 길어 상세 내용을 화면에 표시했습니다."


# ResponsePresentation: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class ResponsePresentation:
    # kind: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    kind: str
    # summary_text: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    summary_text: str
    # detail_text: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    detail_text: str
    # speech_text: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    speech_text: str
    # rulebook_version: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    rulebook_version: int
    # rulebook_hash: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    rulebook_hash: str
    # style_exception에 문자열을 대입합니다.
    style_exception: str = "none"
    # fallback을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    fallback: bool = False


# one_sentence(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text, limit.
# 반환 타입 힌트: 참/거짓(bool).
def one_sentence(text: str, limit: int) -> bool:
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if not text.strip() or len(text) > limit or "\n" in text or "```" in text:
        # False을 반환하고 이 함수의 실행을 끝냅니다.
        return False
    # re.sub()의 반환값을 cleaned에 대입합니다.
    cleaned = re.sub(r"https?://\S+", "URL", text)
    # re.sub()의 반환값을 cleaned에 대입합니다.
    cleaned = re.sub(r"(?<=\d)\.(?=\d)", "·", cleaned)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return not re.search(r"[.!?\u3002\uff01\uff1f][\"'\u2019\u201d)]*\s*[^\s.!?]", cleaned)


# wants_detail(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text.
# 반환 타입 힌트: 참/거짓(bool).
def wants_detail(text: str) -> bool:
    # Only the current, explicit user instruction, never model output or retrieved content.
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return bool(
        re.fullmatch(
            r"[^\n<>\"']*?(?:자세히|상세히|상세하게)\s*(?:설명|알려|말해|읽어)[^\n<>\"']*", text
        )
    ) and not any(word in text for word in ("하지 마", "하지마", "말고", "문서", "인용"))


# present(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: outcome, rulebook, user_text.
# 반환 타입 힌트: ResponsePresentation.
def present(outcome: TurnOutcome, rulebook: Rulebook, user_text: str = "") -> ResponsePresentation:
    # outcome.text.strip()의 반환값을 raw에 대입합니다.
    raw = outcome.text.strip()
    # 오른쪽 식을 계산한 값을 summary에 대입합니다.
    summary = raw
    # 오른쪽 식을 계산한 값을 kind에 대입합니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    kind = "answer" if outcome.ok else "error"
    # exception에 문자열을 대입합니다.
    exception = "none"
    # fallback을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    fallback = False
    # 오른쪽 식을 계산한 값을 verdict에 대입합니다.
    verdict = outcome.pending_approval
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: outcome.intent_confirmation.
    if outcome.intent_confirmation:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ResponsePresentation(
            "approval", raw, "", raw, rulebook.version, rulebook.sha256, "safety"
        )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: verdict is not None.
    if verdict is not None:
        # 언패킹: 오른쪽 결과를 순서대로 (kind, exception)에 나누어 담습니다.
        kind, exception = "approval", "safety"
        # Exact target and warnings remain visible and audible, including ambiguous paths.
        # 오른쪽 식을 계산한 값을 summary에 대입합니다.
        # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
        summary = f"{verdict.display}\n{verdict.reason}"
        # 오른쪽 식을 계산한 값을 speech에 대입합니다.
        speech = summary + " 자비스를 부른 뒤 허용 또는 취소라고 말해 주세요."
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: verdict.risk == 'high'.
        if verdict.risk == "high":
            # 오른쪽 식을 계산한 값을 speech에 대입합니다.
            speech = summary + " 화면에서 확인 문구를 직접 입력해 주세요."
    else:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: outcome.steps.
        if outcome.steps:
            # sum()의 반환값을 done에 대입합니다.
            done = sum(step.state == "succeeded" for step in outcome.steps)
            # 오른쪽 식을 계산한 값을 summary에 대입합니다.
            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
            summary = (
                f"작업 {done}단계를 완료했습니다."
                if outcome.ok
                else f"완료된 단계는 {done}개이며 나머지 작업은 완료되지 않았습니다."
            )
            # kind에 문자열을 대입합니다.
            kind = "tool_result"
        # 언패킹: 오른쪽 결과를 순서대로 (body, marker, status)에 나누어 담습니다.
        body, marker, status = raw.rpartition("\n\n상태: ")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if (
            marker
            and status in {"확실", "상충", "근거 부족"}
            and one_sentence(body, rulebook.max_chars)
        ):
            # 오른쪽 식을 계산한 값을 summary에 대입합니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            summary = f"{body.rstrip('.')} ({status})."
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: outcome.tool_name == 'open_app' and
        # outcome.ok.
        if outcome.tool_name == "open_app" and outcome.ok:
            # kind에 문자열을 대입합니다.
            kind = "tool_result"
            # 오른쪽 식을 계산한 값을 summary에 대입합니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            summary = f"{outcome.tool_label or '앱'} 실행을 요청했습니다."
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: outcome.tool_name == 'close_app' and
        # outcome.ok.
        elif outcome.tool_name == "close_app" and outcome.ok:
            # kind에 문자열을 대입합니다.
            kind = "tool_result"
            # 오른쪽 식을 계산한 값을 summary에 대입합니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            summary = f"{outcome.tool_label or '앱'} 종료했습니다."
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        elif outcome.ok and outcome.tool_name in {"create_file", "open_folder", "open_url"}:
            # kind에 문자열을 대입합니다.
            kind = "tool_result"
            # 오른쪽 식을 계산한 값을 summary에 대입합니다.
            summary = {
                "create_file": "파일을 만들었습니다.",
                "open_folder": "폴더 열기를 요청했습니다.",
                "open_url": "웹 페이지 열기를 요청했습니다.",
            }[outcome.tool_name]
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not one_sentence(summary,
        # rulebook.max_chars).
        if outcome.grounding_status:
            first = raw.split("\n\n", 1)[0]
            if outcome.grounding_status == "근거 확인":
                summary = re.sub(r"\s*\[\d+\]", "", first).rstrip(". ") + " (근거 확인)."
            elif outcome.grounding_status == "상충":
                summary = "검색된 자료가 상충하여 답변을 보류했습니다."
            else:
                summary = "근거가 부족하여 답변을 보류했습니다."
        if not one_sentence(summary, rulebook.max_chars):
            # fallback을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
            fallback = True
            # 오른쪽 식을 계산한 값을 summary에 대입합니다.
            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
            summary = (
                "작업을 완료하지 못했으니 상세 내용을 확인해 주세요."
                if not outcome.ok
                else FALLBACK
            )
        # 오른쪽 식을 계산한 값을 speech에 대입합니다.
        speech = summary
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if (
            wants_detail(user_text)
            or user_text.strip() in {"/details", "/status", "/apps"}
            or user_text.startswith(("/commands", "/recall"))
        ):
            # exception에 문자열을 대입합니다.
            exception = "explicit_detail"
            # 오른쪽 식을 계산한 값을 summary에 대입합니다.
            summary = raw
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: any((word in user_text for word in
            # ('말로', '음성으로',
            # '읽어'))).
            if any(word in user_text for word in ("말로", "음성으로", "읽어")):
                # 오른쪽 식을 계산한 값을 speech에 대입합니다.
                speech = raw
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    if outcome.answer_mode == "general":
        label = "문서 근거 없는 일반 답변"
        if label not in summary:
            summary = f"{label}: {summary}"
        if label not in speech:
            speech = f"{label}: {speech}"
        kind = "general_answer"
    return ResponsePresentation(
        kind,
        summary,
        raw if raw != summary else "",
        speech,
        rulebook.version,
        rulebook.sha256,
        exception,
        fallback,
    )

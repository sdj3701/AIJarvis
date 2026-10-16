# 파이썬 공부 | scripts/app/memory/summarizer.py
# 세션이 끝나면 대화를 요약하고 기억으로 남길 후보를 추출합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Session-end summarization into summary records and fact candidates."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from app.core.context import RequestContext
from app.core.errors import LLMBadResponse
from app.core.ids import PrefixedIdFactory
from app.llm.base import LLMClient, Message
from app.memory.models import (
    FactCandidate,
    MemoryRecord,
    SessionSummary,
    new_fact_id,
    new_summary_id,
    validate_memory_key,
)
from app.memory.store import RawRecord, SQLiteSessionStore
from app.privacy.gate import PrivacyGate

# re.compile()의 반환값을 _SUMMARY_JSON_RE에 대입합니다.
_SUMMARY_JSON_RE = re.compile(r"\{[\s\S]*\}")


# EventSink: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class EventSink(Protocol):
    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


# SummarizerSettings: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class SummarizerSettings:
    # model_label: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    model_label: str
    # prompt_version에 문자열을 대입합니다.
    prompt_version: str = "1"


# _conversation_lines(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: records, gate.
# 반환 타입 힌트: list[str].
def _conversation_lines(records: Sequence[RawRecord], gate: PrivacyGate) -> list[str]:
    # lines에 리스트(순서가 있고 수정 가능)을 대입합니다.
    lines: list[str] = []
    # for 반복문: 대상의 항목을 하나씩 record에 대입하며 아래 블록을 실행합니다.
    for record in records:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: record.role not in {'user',
        # 'assistant'}.
        if record.role not in {"user", "assistant"}:
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # 오른쪽 식을 계산한 값을 label에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        label = "사용자" if record.role == "user" else "자비스"
        # gate.for_summarizer_text()의 반환값을 content에 대입합니다.
        content = gate.for_summarizer_text(record.content)
        # 리스트 끝에 항목 하나를 추가합니다.
        lines.append(f"[{record.turn_id}] {label}: {content}")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return lines


# _build_prompt(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: conversation.
# 반환 타입 힌트: list[Message].
def _build_prompt(conversation: str) -> list[Message]:
    # system에 문자열을 대입합니다.
    system = (
        "당신은 대화 요약기입니다. 아래 대화를 읽고 JSON만 출력하세요.\n"
        "스키마:\n"
        "{\n"
        '  "schema_version": 1,\n'
        '  "summary": "한국어 요약 문장",\n'
        '  "fact_candidates": [\n'
        "    {\n"
        '      "key": "pref.answer_style",\n'
        '      "value": "짧고 근거 포함",\n'
        '      "confidence": 0.7,\n'
        '      "evidence_turn_ids": ["turn_..."]\n'
        "    }\n"
        "  ],\n"
        '  "corrections": [],\n'
        '  "tags": ["tag"]\n'
        "}\n"
        "규칙:\n"
        "- fact_candidates는 evidence_turn_ids가 반드시 있어야 합니다.\n"
        "- key는 identity.|pref.|env.|project.|contact.|fact. 접두사를 사용합니다.\n"
        "- confidence는 0~1입니다.\n"
        "- JSON 외 텍스트는 출력하지 마세요."
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return [
        Message("system", system),
        Message("user", f"대화:\n{conversation}"),
    ]


# _parse_summary_json(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text, session_id.
# 반환 타입 힌트: dict[str, Any].
def _parse_summary_json(text: str, session_id: str) -> dict[str, Any]:
    # _SUMMARY_JSON_RE.search()의 반환값을 match에 대입합니다.
    match = _SUMMARY_JSON_RE.search(text.strip())
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match is None.
    if match is None:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse("요약 JSON을 찾을 수 없습니다.")
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # json.loads()의 반환값을 parsed에 대입합니다.
        parsed = json.loads(match.group(0))
    # json.JSONDecodeError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except json.JSONDecodeError as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse("요약 JSON 파싱에 실패했습니다.") from error
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(parsed, dict).
    if not isinstance(parsed, dict):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse("요약 JSON은 객체여야 합니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: parsed.get('schema_version') != 1.
    if parsed.get("schema_version") != 1:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse("요약 schema_version이 올바르지 않습니다.")
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if not isinstance(parsed.get("summary"), str) or not str(parsed["summary"]).strip():
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse("요약 summary가 비어 있습니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: session_id and parsed.get('session_id')
    # not in {None,
    # session_id}.
    if session_id and parsed.get("session_id") not in {None, session_id}:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse("요약 session_id가 일치하지 않습니다.")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return parsed


# _parse_fact_candidates(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: raw_items.
# 반환 타입 힌트: tuple[FactCandidate, ...].
def _parse_fact_candidates(raw_items: object) -> tuple[FactCandidate, ...]:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(raw_items, list).
    if not isinstance(raw_items, list):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse("fact_candidates는 배열이어야 합니다.")
    # results에 리스트(순서가 있고 수정 가능)을 대입합니다.
    results: list[FactCandidate] = []
    # for 반복문: 대상의 항목을 하나씩 item에 대입하며 아래 블록을 실행합니다.
    for item in raw_items:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(item, dict).
        if not isinstance(item, dict):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("fact_candidates 항목은 객체여야 합니다.")
        # item.get()의 반환값을 key에 대입합니다.
        key = item.get("key")
        # item.get()의 반환값을 value에 대입합니다.
        value = item.get("value")
        # item.get()의 반환값을 evidence에 대입합니다.
        evidence = item.get("evidence_turn_ids")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(key, str) or not
        # isinstance(value, str).
        if not isinstance(key, str) or not isinstance(value, str):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("fact candidate key/value가 올바르지 않습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not validate_memory_key(key).
        if not validate_memory_key(key):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("fact candidate key namespace가 올바르지 않습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(evidence, list) or not
        # evidence.
        if not isinstance(evidence, list) or not evidence:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("evidence_turn_ids가 필요합니다.")
        # tuple()의 반환값을 turn_ids에 대입합니다.
        turn_ids = tuple(str(turn_id) for turn_id in evidence)
        # item.get()의 반환값을 confidence_raw에 대입합니다.
        confidence_raw = item.get("confidence", 0.5)
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # float()의 반환값을 confidence에 대입합니다.
            confidence = float(confidence_raw)
        # (TypeError, ValueError)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except (TypeError, ValueError) as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("confidence가 올바르지 않습니다.") from error
        # str()의 반환값을 candidate_id에 대입합니다.
        candidate_id = str(item.get("id") or new_fact_id())
        # 리스트 끝에 항목 하나를 추가합니다.
        results.append(
            FactCandidate(
                id=candidate_id,
                key=key,
                value=value.strip(),
                status="candidate",
                confidence=confidence,
                evidence_turn_ids=turn_ids,
            )
        )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return tuple(results)


# SessionSummarizer: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class SessionSummarizer:
    # llm: LLMClient 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    llm: LLMClient
    # store: SQLiteSessionStore 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    store: SQLiteSessionStore
    # gate: PrivacyGate 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    gate: PrivacyGate
    # ids: PrefixedIdFactory 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ids: PrefixedIdFactory
    # settings: SummarizerSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    settings: SummarizerSettings
    # events을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    events: EventSink | None = None

    # summarize_session(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: session_id, ctx, timeout_s, temperature, max_output_tokens.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: SessionSummary | None.
    def summarize_session(
        self,
        session_id: str,
        *,
        ctx: RequestContext,
        timeout_s: float = 120.0,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
    ) -> SessionSummary | None:
        # self.store.get_session()의 반환값을 session에 대입합니다.
        session = self.store.get_session(session_id)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: session is None.
        if session is None:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None

        # self.store.read_raw()의 반환값을 raw에 대입합니다.
        raw = self.store.read_raw(session_id)
        # _conversation_lines()의 반환값을 conversation_lines에 대입합니다.
        conversation_lines = _conversation_lines(raw.records, self.gate)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not conversation_lines.
        if not conversation_lines:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None

        # _build_prompt()의 반환값을 messages에 대입합니다.
        messages = _build_prompt("\n".join(conversation_lines))

        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # self.llm.complete()의 반환값을 response에 대입합니다.
            response = self.llm.complete(
                messages=messages,
                timeout_s=timeout_s,
                ctx=ctx,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: response.text is None.
            if response.text is None:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise LLMBadResponse("요약 응답 본문이 없습니다.")
            # _parse_summary_json()의 반환값을 parsed에 대입합니다.
            parsed = _parse_summary_json(response.text, session_id)
            # _parse_fact_candidates()의 반환값을 fact_candidates에 대입합니다.
            fact_candidates = _parse_fact_candidates(parsed.get("fact_candidates", []))
            # _parse_fact_candidates()의 반환값을 corrections에 대입합니다.
            corrections = _parse_fact_candidates(parsed.get("corrections", []))
        # (LLMBadResponse, ValueError)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
        # 담깁니다.
        except (LLMBadResponse, ValueError) as error:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.events is not None.
            if self.events is not None:
                # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
                self.events.emit(
                    "session.summary_failed",
                    {
                        "session_id": session_id,
                        "error_type": type(error).__name__,
                        "user_message": getattr(error, "user_message", str(error)),
                    },
                )
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None

        # ctx.clock.now()의 반환값을 now에 대입합니다.
        now = ctx.clock.now()
        # new_summary_id()의 반환값을 summary_id에 대입합니다.
        summary_id = new_summary_id()
        # MemoryRecord()의 반환값을 summary_record에 대입합니다.
        summary_record = MemoryRecord(
            id=summary_id,
            schema_version=1,
            kind="summary",
            key=None,
            value=str(parsed["summary"]).strip(),
            status="confirmed",
            source_session_id=session_id,
            source_turn_id=None,
            source_kind="summarizer",
            created_at=now,
            updated_at=now,
            expires_at=None,
            sensitivity="normal",
            supersedes=None,
            tags=tuple(str(tag) for tag in parsed.get("tags", []) if isinstance(tag, str)),
        )
        # 언패킹: 오른쪽 결과를 순서대로 (gated_summary, _)에 나누어 담습니다.
        gated_summary, _ = self.gate.for_memory_write(summary_record, source_kind="summarizer")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: gated_summary is None.
        if gated_summary is None:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.events is not None.
            if self.events is not None:
                # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
                self.events.emit(
                    "session.summary_failed",
                    {"session_id": session_id, "error_type": "PrivacyBlocked"},
                )
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None

        # self.store.put_record()을 호출해 작업을 수행합니다.
        self.store.put_record(gated_summary)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.events is not None.
        if self.events is not None:
            # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
            self.events.emit(
                "memory.write",
                {
                    "record_id": summary_id,
                    "kind": "summary",
                    "status": "confirmed",
                    "source_kind": "summarizer",
                },
            )

        # stored_candidates에 리스트(순서가 있고 수정 가능)을 대입합니다.
        stored_candidates: list[FactCandidate] = []
        # for 반복문: 대상의 항목을 하나씩 candidate에 대입하며 아래 블록을 실행합니다.
        for candidate in fact_candidates:
            # MemoryRecord()의 반환값을 record에 대입합니다.
            record = MemoryRecord(
                id=candidate.id,
                schema_version=1,
                kind="fact",
                key=candidate.key,
                value=candidate.value,
                status="candidate",
                source_session_id=session_id,
                source_turn_id=candidate.evidence_turn_ids[0],
                source_kind="summarizer",
                created_at=now,
                updated_at=now,
                expires_at=None,
                sensitivity="normal",
                supersedes=None,
                tags=("summarizer",),
            )
            # 언패킹: 오른쪽 결과를 순서대로 (gated, _)에 나누어 담습니다.
            gated, _ = self.gate.for_memory_write(record, source_kind="summarizer")
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: gated is None.
            if gated is None:
                # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                continue
            # self.store.put_record()을 호출해 작업을 수행합니다.
            self.store.put_record(gated)
            # 리스트 끝에 항목 하나를 추가합니다.
            stored_candidates.append(candidate)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.events is not None.
            if self.events is not None:
                # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
                self.events.emit(
                    "memory.write",
                    {
                        "record_id": gated.id,
                        "kind": gated.kind,
                        "status": "candidate",
                        "source_kind": "summarizer",
                    },
                )

        # for 반복문: 대상의 항목을 하나씩 candidate에 대입하며 아래 블록을 실행합니다.
        for candidate in corrections:
            # MemoryRecord()의 반환값을 record에 대입합니다.
            record = MemoryRecord(
                id=candidate.id,
                schema_version=1,
                kind="correction",
                key=candidate.key,
                value=candidate.value,
                status="candidate",
                source_session_id=session_id,
                source_turn_id=candidate.evidence_turn_ids[0],
                source_kind="summarizer",
                created_at=now,
                updated_at=now,
                expires_at=None,
                sensitivity="normal",
                supersedes=None,
                tags=("summarizer", "correction"),
            )
            # 언패킹: 오른쪽 결과를 순서대로 (gated, _)에 나누어 담습니다.
            gated, _ = self.gate.for_memory_write(record, source_kind="summarizer")
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: gated is None.
            if gated is None:
                # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                continue
            # self.store.put_record()을 호출해 작업을 수행합니다.
            self.store.put_record(gated)
            # 리스트 끝에 항목 하나를 추가합니다.
            stored_candidates.append(candidate)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.events is not None.
            if self.events is not None:
                # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
                self.events.emit(
                    "memory.write",
                    {
                        "record_id": gated.id,
                        "kind": gated.kind,
                        "status": "candidate",
                        "source_kind": "summarizer",
                    },
                )

        # 오른쪽 식을 계산한 값을 cost에 대입합니다.
        cost = response.usage.cost_usd
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # Decimal()의 반환값을 cost_decimal에 대입합니다.
            cost_decimal = Decimal(str(parsed.get("cost_usd", cost)))
        # (InvalidOperation, TypeError)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
        # 담깁니다.
        except (InvalidOperation, TypeError):
            # 오른쪽 식을 계산한 값을 cost_decimal에 대입합니다.
            cost_decimal = cost

        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return SessionSummary(
            schema_version=1,
            session_id=session_id,
            summary_record_id=summary_id,
            summary=gated_summary.value,
            turn_count=session.turn_count,
            fact_candidates=tuple(stored_candidates),
            corrections=corrections,
            tags=gated_summary.tags,
            raw_path=str(session.raw_path),
            generated_by={
                "model": self.settings.model_label,
                "prompt_version": self.settings.prompt_version,
            },
            cost_usd=cost_decimal,
        )

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

_SUMMARY_JSON_RE = re.compile(r"\{[\s\S]*\}")


class EventSink(Protocol):
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class SummarizerSettings:
    model_label: str
    prompt_version: str = "1"


def _conversation_lines(records: Sequence[RawRecord], gate: PrivacyGate) -> list[str]:
    lines: list[str] = []
    for record in records:
        if record.role not in {"user", "assistant"}:
            continue
        label = "사용자" if record.role == "user" else "자비스"
        content = gate.for_summarizer_text(record.content)
        lines.append(f"[{record.turn_id}] {label}: {content}")
    return lines


def _build_prompt(conversation: str) -> list[Message]:
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
    return [
        Message("system", system),
        Message("user", f"대화:\n{conversation}"),
    ]


def _parse_summary_json(text: str, session_id: str) -> dict[str, Any]:
    match = _SUMMARY_JSON_RE.search(text.strip())
    if match is None:
        raise LLMBadResponse("요약 JSON을 찾을 수 없습니다.")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise LLMBadResponse("요약 JSON 파싱에 실패했습니다.") from error
    if not isinstance(parsed, dict):
        raise LLMBadResponse("요약 JSON은 객체여야 합니다.")
    if parsed.get("schema_version") != 1:
        raise LLMBadResponse("요약 schema_version이 올바르지 않습니다.")
    if not isinstance(parsed.get("summary"), str) or not str(parsed["summary"]).strip():
        raise LLMBadResponse("요약 summary가 비어 있습니다.")
    if session_id and parsed.get("session_id") not in {None, session_id}:
        raise LLMBadResponse("요약 session_id가 일치하지 않습니다.")
    return parsed


def _parse_fact_candidates(raw_items: object) -> tuple[FactCandidate, ...]:
    if not isinstance(raw_items, list):
        raise LLMBadResponse("fact_candidates는 배열이어야 합니다.")
    results: list[FactCandidate] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise LLMBadResponse("fact_candidates 항목은 객체여야 합니다.")
        key = item.get("key")
        value = item.get("value")
        evidence = item.get("evidence_turn_ids")
        if not isinstance(key, str) or not isinstance(value, str):
            raise LLMBadResponse("fact candidate key/value가 올바르지 않습니다.")
        if not validate_memory_key(key):
            raise LLMBadResponse("fact candidate key namespace가 올바르지 않습니다.")
        if not isinstance(evidence, list) or not evidence:
            raise LLMBadResponse("evidence_turn_ids가 필요합니다.")
        turn_ids = tuple(str(turn_id) for turn_id in evidence)
        confidence_raw = item.get("confidence", 0.5)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError) as error:
            raise LLMBadResponse("confidence가 올바르지 않습니다.") from error
        candidate_id = str(item.get("id") or new_fact_id())
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
    return tuple(results)


@dataclass(frozen=True, slots=True)
class SessionSummarizer:
    llm: LLMClient
    store: SQLiteSessionStore
    gate: PrivacyGate
    ids: PrefixedIdFactory
    settings: SummarizerSettings
    events: EventSink | None = None

    def summarize_session(
        self,
        session_id: str,
        *,
        ctx: RequestContext,
        timeout_s: float = 120.0,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
    ) -> SessionSummary | None:
        session = self.store.get_session(session_id)
        if session is None:
            return None

        raw = self.store.read_raw(session_id)
        conversation_lines = _conversation_lines(raw.records, self.gate)
        if not conversation_lines:
            return None

        messages = _build_prompt("\n".join(conversation_lines))

        try:
            response = self.llm.complete(
                messages=messages,
                timeout_s=timeout_s,
                ctx=ctx,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
            if response.text is None:
                raise LLMBadResponse("요약 응답 본문이 없습니다.")
            parsed = _parse_summary_json(response.text, session_id)
            fact_candidates = _parse_fact_candidates(parsed.get("fact_candidates", []))
            corrections = _parse_fact_candidates(parsed.get("corrections", []))
        except (LLMBadResponse, ValueError) as error:
            if self.events is not None:
                self.events.emit(
                    "session.summary_failed",
                    {
                        "session_id": session_id,
                        "error_type": type(error).__name__,
                        "user_message": getattr(error, "user_message", str(error)),
                    },
                )
            return None

        now = ctx.clock.now()
        summary_id = new_summary_id()
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
        gated_summary, _ = self.gate.for_memory_write(summary_record, source_kind="summarizer")
        if gated_summary is None:
            if self.events is not None:
                self.events.emit(
                    "session.summary_failed",
                    {"session_id": session_id, "error_type": "PrivacyBlocked"},
                )
            return None

        self.store.put_record(gated_summary)
        if self.events is not None:
            self.events.emit(
                "memory.write",
                {
                    "record_id": summary_id,
                    "kind": "summary",
                    "status": "confirmed",
                    "source_kind": "summarizer",
                },
            )

        stored_candidates: list[FactCandidate] = []
        for candidate in fact_candidates:
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
            gated, _ = self.gate.for_memory_write(record, source_kind="summarizer")
            if gated is None:
                continue
            self.store.put_record(gated)
            stored_candidates.append(candidate)
            if self.events is not None:
                self.events.emit(
                    "memory.write",
                    {
                        "record_id": gated.id,
                        "kind": gated.kind,
                        "status": "candidate",
                        "source_kind": "summarizer",
                    },
                )

        for candidate in corrections:
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
            gated, _ = self.gate.for_memory_write(record, source_kind="summarizer")
            if gated is None:
                continue
            self.store.put_record(gated)
            stored_candidates.append(candidate)
            if self.events is not None:
                self.events.emit(
                    "memory.write",
                    {
                        "record_id": gated.id,
                        "kind": gated.kind,
                        "status": "candidate",
                        "source_kind": "summarizer",
                    },
                )

        cost = response.usage.cost_usd
        try:
            cost_decimal = Decimal(str(parsed.get("cost_usd", cost)))
        except (InvalidOperation, TypeError):
            cost_decimal = cost

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

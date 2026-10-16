# 파이썬 공부 | scripts/app/orchestrator/fast_path.py
# 단순 팩트 및 기억 질의에 대해 Ollama LLM 호출 없이 즉시 답변을 반환하는 고속 경로(Fast-Path)입니다.

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.memory.store import SQLiteSessionStore


def normalize_query(text: str) -> str:
    """텍스트를 비교하기 쉽게 NFKC 정규화하고 구두점을 제거합니다."""
    normalized = unicodedata.normalize("NFKC", text).casefold().strip()
    return re.sub(r"[?!.,~]+$", "", normalized).strip()


@dataclass(frozen=True, slots=True)
class FastPathMatch:
    """Fast-Path 매칭 결과입니다."""
    text: str
    fact_key: str
    fact_value: str
    source: str = "memory_fact"


class FactFastPath:
    """기억 DB에 저장된 팩트를 기반으로 Ollama 없이 즉각 답변을 생성하는 핸들러입니다."""

    def __init__(self, sessions: SQLiteSessionStore | None = None) -> None:
        self._sessions = sessions

    def try_match(self, text: str) -> FastPathMatch | None:
        """사용자 입력이 팩트 질의인지 검사하고 매칭 시 즉시 답변을 반환합니다."""
        if not text or len(text.strip()) > 100:
            return None

        # 명령어, 도구 호출, 다단계 작업 등은 Fast-Path 대상에서 제외
        if text.startswith(("/", "!", "@")) or any(
            w in text for w in ("실행", "열어", "닫아", "만들어", "삭제", "검색해", "찾아줘", "요약해", "비교해", "설명해", "왜")
        ):
            return None

        norm = normalize_query(text)

        # 1. 대한민국 수도 질의 매칭
        if ("수도" in norm) and any(k in norm for k in ("대한민국", "한국", "우리나라")):
            fact_val = self._lookup_fact("fact.capital_of_korea") or "서울"
            answer = f"대한민국의 수도는 {fact_val}입니다."
            return FastPathMatch(text=answer, fact_key="fact.capital_of_korea", fact_value=fact_val)

        # 2. 이름 질의 매칭
        if any(norm == w or norm.startswith(w) for w in ("너 이름", "이름이 뭐야", "네 이름", "이름이 뭐니", "너의 이름", "자비스 이름")):
            fact_val = self._lookup_fact("env.name") or "자비스"
            answer = f"제 이름은 {fact_val}입니다."
            return FastPathMatch(text=answer, fact_key="env.name", fact_value=fact_val)

        # 3. 운영체제 / OS 질의 매칭
        if any(w in norm for w in ("운영체제", "os가 뭐야", "현재 os", "어떤 os", "사용 os")):
            fact_val = self._lookup_fact("env.os") or "Windows PC"
            answer = f"현재 운영체제는 {fact_val}입니다."
            return FastPathMatch(text=answer, fact_key="env.os", fact_value=fact_val)

        # 4. 역할 질의 매칭
        if any(w in norm for w in ("너 역할", "역할이 뭐야", "무슨 역할", "정체가 뭐야", "뭐하는 애야")):
            fact_val = self._lookup_fact("env.role") or "개인 AI 비서"
            answer = f"저는 {fact_val}입니다."
            return FastPathMatch(text=answer, fact_key="env.role", fact_value=fact_val)

        # 5. DB에 등록된 커스텀 팩트 매칭 시도
        custom_match = self._match_dynamic_facts(norm)
        if custom_match is not None:
            return custom_match

        return None

    def _lookup_fact(self, key: str) -> str | None:
        """기억 DB에서 지정된 키의 팩트 값을 조회합니다."""
        if self._sessions is None:
            return None
        try:
            with self._sessions._connection() as conn:
                row = conn.execute(
                    "SELECT value FROM records WHERE key = ? AND status = 'confirmed' AND deleted_at IS NULL LIMIT 1;",
                    (key,),
                ).fetchone()
                if row and row[0]:
                    return str(row[0]).strip()
        except Exception:
            return None
        return None

    def _match_dynamic_facts(self, norm: str) -> FastPathMatch | None:
        """기억 DB의 팩트들을 순회하여 특정 키워드와 1:1 매칭되는 팩트가 있는지 확인합니다."""
        if self._sessions is None:
            return None
        try:
            with self._sessions._connection() as conn:
                rows = conn.execute(
                    "SELECT key, value FROM records WHERE kind = 'fact' AND status = 'confirmed' AND deleted_at IS NULL LIMIT 100;"
                ).fetchall()
                for key, val in rows:
                    if not key or not val:
                        continue
                    # key 예: fact.mle_meanings -> mle_meanings
                    sub_key = key.split(".", 1)[-1].replace("_", " ")
                    if sub_key in norm and any(q in norm for q in ("뜻", "의미", "뭐야", "알려줘", "상태")):
                        return FastPathMatch(
                            text=f"{sub_key}의 내용은 다음과 같습니다: {val}",
                            fact_key=key,
                            fact_value=str(val),
                        )
        except Exception:
            return None
        return None

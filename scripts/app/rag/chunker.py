# 파이썬 공부 | scripts/app/rag/chunker.py
# 긴 문서를 일정 길이로 나눕니다. 조각 일부를 겹쳐 문맥이 끊기는 것을 줄입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Recursive, token-bounded document chunks and legacy conversation slicing."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from app.rag.local_embedder import EmbeddingInputTooLong


# TextChunk: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class TextChunk:
    # 조각 번호와 원문에서의 위치를 함께 저장하면 검색 결과를 원문과 연결할 수 있습니다.
    # ordinal: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ordinal: int
    # text: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    text: str
    # start_char: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    start_char: int
    # end_char: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    end_char: int
    title: str = ""
    token_count: int | None = None
    tokenizer_id: str = "character-v1"


# 문서를 잘라 TextChunk 튜플로 반환합니다.
# 예: 길이 10, 조각 6, 겹침 2이면 [0:6], [4:10] 두 조각입니다.
# 입력: text, chunk_chars, overlap_chars.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: tuple[TextChunk, ...].
def chunk_text(text: str, *, chunk_chars: int, overlap_chars: int) -> tuple[TextChunk, ...]:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: chunk_chars <= 0.
    if chunk_chars <= 0:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("chunk_chars는 1 이상이어야 합니다")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: overlap_chars < 0 or overlap_chars >=
    # chunk_chars.
    if overlap_chars < 0 or overlap_chars >= chunk_chars:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("overlap_chars는 0 이상이고 chunk_chars보다 작아야 합니다")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not text.
    if not text:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ()

    # 완성한 TextChunk 객체들을 순서대로 담을 빈 리스트입니다.
    chunks: list[TextChunk] = []
    # 첫 조각은 문자열의 0번 위치부터 시작합니다. 인덱스는 0부터 셉니다.
    start = 0
    # 조각 번호도 0부터 붙입니다.
    ordinal = 0
    # len(text)는 문자열의 길이입니다. 마지막 조각의 경계를 계산할 때 씁니다.
    length = len(text)
    # 조각 길이에서 겹칠 길이를 빼면 다음 시작점까지 이동할 거리가 됩니다.
    step = chunk_chars - overlap_chars
    # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
    while start < length:
        # min은 더 작은 값을 선택합니다. 마지막 조각이 원문 길이를 넘지 않게 합니다.
        end = min(start + chunk_chars, length)
        # 리스트 끝에 항목 하나를 추가합니다.
        chunks.append(
            TextChunk(
                ordinal=ordinal,
                # 시작 위치는 포함하고 끝 위치는 제외합니다. 예: text[0:3]은 처음 세 글자.
                text=text[start:end],
                start_char=start,
                end_char=end,
            )
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: end >= length.
        if end >= length:
            # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
            break
        # start += step은 start = start + step입니다. 다음 조각의 시작 위치로 이동합니다.
        start += step
        # 다음 조각에 붙일 번호를 1 증가시킵니다.
        ordinal += 1
    # 리스트를 튜플로 바꿔 반환합니다. 호출한 쪽에서 조각 묶음에 항목을 추가·삭제할 수 없습니다.
    return tuple(chunks)


DOCUMENT_CHUNK_POLICY = "recursive-context-v4"


def _heading_only(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    return not lines or all(re.match(r"^#{1,6}\s+", line) for line in lines)


def _sections(text: str, title: str) -> list[tuple[int, int, str]]:
    headings = [(0, title)]
    stack: list[tuple[int, str]] = []
    fence = ""
    offset = 0
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            if not fence:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = ""
        elif not fence and (match := re.match(r"^(#{1,6})\s+(.+?)\s*$", line)):
            depth = len(match[1])
            stack = [(d, s) for d, s in stack if d < depth]
            stack.append((depth, match[2]))
            headings.append((offset, title + " > " + " > ".join(s for _, s in stack)))
        offset += len(line)
    sections = [
        (start, headings[i + 1][0] if i + 1 < len(headings) else len(text), name)
        for i, (start, name) in enumerate(headings)
        if start < (headings[i + 1][0] if i + 1 < len(headings) else len(text))
    ]
    # Carry empty parent headings into the next section with body text. Their
    # hierarchy remains in its title, but they never become standalone hits.
    result: list[tuple[int, int, str]] = []
    pending: int | None = None
    for start, end, name in sections:
        if _heading_only(text[start:end]):
            if pending is None:
                pending = start
            continue
        result.append((pending if pending is not None else start, end, name))
        pending = None
    if pending is not None and result:
        start, _, name = result[-1]
        result[-1] = (start, len(text), name)
    return result


def _block_ends(text: str, start: int, end: int) -> list[int]:
    """Paragraphs and simple Markdown blocks; never split a fitting fence/table."""
    ends = {end}
    offset = start
    fence = ""
    previous_kind = "prose"
    for line in text[start:end].splitlines(keepends=True):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = ""
                ends.add(offset + len(line))
        elif marker:
            ends.add(offset)
            fence = marker[1]
        else:
            kind = "lines" if re.match(r"^\s*(?:\||[-*+]\s|\d+[.)]\s+(?!\d))", line) else "prose"
            if kind != previous_kind:
                ends.add(offset)
            if not line.strip():
                ends.add(offset + len(line))
            previous_kind = kind
        offset += len(line)
    return sorted(p for p in ends if start < p <= end)


def document_chunks(
    text: str,
    *,
    title: str,
    count_tokens: Callable[[str, str], int] | None,
    tokenizer_id: str,
    max_tokens: int = 384,
    overlap_tokens: int = 48,
    max_chars: int = 1200,
    overlap_chars: int = 150,
) -> tuple[TextChunk, ...]:
    """Document-only route: sections -> paragraphs -> sentences -> words -> chars.

    Each fitting unit stays intact. Adjacent units in the same section are packed
    together; overlap copies whole trailing units only when the next unit still
    fits. Token counts include the document prefix/title. Character limits also
    bound calls to the model. Lexical-only indexing never claims token validation.
    All chunks are exact contiguous source slices, including whitespace.
    """
    if max_tokens <= 0 or not 0 <= overlap_tokens < max_tokens:
        raise ValueError("Invalid token chunk budget")
    if max_chars <= 0 or not 0 <= overlap_chars < max_chars:
        raise ValueError("Invalid character chunk budget")
    result: list[TextChunk] = []
    sections = _sections(text, title)
    packed: list[tuple[int, int, str]] = []
    group_count = 0
    last_parent = ""
    for start, end, name in sections:
        parent = name.rsplit(" > ", 1)[0]
        legal = bool(re.search(r"^### 제\d+조", text[start:end], re.M))
        small = (
            legal
            and end - start <= max_chars // 4
            and (count_tokens(text[start:end], parent) <= max_tokens // 4 if count_tokens else True)
        )
        if small and packed and last_parent == parent and 0 < group_count < 4:
            previous_start = packed[-1][0]
            combined = text[previous_start:end]
            if len(combined) <= max_chars and (
                not count_tokens or count_tokens(combined, parent) <= max_tokens
            ):
                packed[-1] = (previous_start, end, parent)
                group_count += 1
                continue
        packed.append((start, end, name))
        group_count = 1 if small else 0
        last_parent = parent
    for section_start, section_end, chunk_title in packed:
        overhead = count_tokens("", chunk_title) if count_tokens else 0
        if count_tokens and overhead >= max_tokens:
            raise ValueError("Document title leaves no token budget")

        @lru_cache(maxsize=2048)
        def tokens(start: int, end: int, section_title: str = chunk_title) -> int:
            try:
                return count_tokens(text[start:end], section_title) if count_tokens else 0
            except EmbeddingInputTooLong:
                # Counting uses model inference. An oversized candidate must be
                # split further, not mistaken for an unavailable model. This
                # sentinel is only used for rejected spans, never stored counts.
                return max_tokens + 1

        def fits(start: int, end: int) -> bool:
            return end - start <= max_chars and tokens(start, end) <= max_tokens

        def split(start: int, end: int, level: int = 0) -> list[tuple[int, int]]:
            if fits(start, end):
                return [(start, end)]
            if level == 0:
                ends = _block_ends(text, start, end)
            elif level == 1:
                block = text[start:end]
                # Oversized tables/lists/fences prefer complete lines over punctuation.
                pattern = (
                    r"\n"
                    if re.match(r"^\s*(?:`{3,}|~{3,}|\||[-*+]\s|\d+[.)]\s+(?!\d))", block)
                    else r"(?<!\d)[.!?。\uff01\uff1f](?:\s+|$)"
                )
                ends = [start + m.end() for m in re.finditer(pattern, block)]
                ends.append(end)
            elif level == 2:
                ends = [start + m.end() for m in re.finditer(r"\s+", text[start:end])]
                ends.append(end)
            else:
                # No usable boundary: find fitting source spans without discarding
                # any Unicode code points. Always verify the accepted token count;
                # tokenizer counts need not be strictly monotonic with prefix length.
                parts = []
                while start < end:
                    low, high, best = start + 1, min(start + max_chars, end), start
                    while low <= high:
                        middle = (low + high) // 2
                        if fits(start, middle):
                            best, low = middle, middle + 1
                        else:
                            high = middle - 1
                    if best == start:
                        raise ValueError("Cannot fit a source character in the token budget")
                    parts.append((start, best))
                    start = best
                return parts
            parts = []
            for boundary in sorted(set(ends)):
                if boundary > start:
                    parts.extend(split(start, boundary, level + 1))
                    start = boundary
            return parts

        def emit(units: list[tuple[int, int]], section_title: str = chunk_title) -> None:
            start, end = units[0][0], units[-1][1]
            if _heading_only(text[start:end]):
                return
            result.append(
                TextChunk(
                    len(result),
                    text[start:end],
                    start,
                    end,
                    section_title,
                    tokens(start, end) if count_tokens else None,
                    tokenizer_id,
                )
            )

        pending: list[tuple[int, int]] = []
        for unit in split(section_start, section_end):
            if pending and not fits(pending[0][0], unit[1]):
                emit(pending)
                # Overlap is a target, not permission to break an intact paragraph.
                # Drop at least one unit so successive chunks always move forward.
                tail: list[tuple[int, int]] = []
                for i in range(1, len(pending)):
                    begin, finish = pending[i][0], pending[-1][1]
                    if (
                        finish - begin <= overlap_chars
                        and (not count_tokens or tokens(begin, finish) - overhead <= overlap_tokens)
                        and fits(begin, unit[1])
                    ):
                        tail = pending[i:]
                        break
                pending = tail
            pending.append(unit)
        if pending:
            emit(pending)
    return tuple(result)


# Compatibility for benchmark/older callers. New document ingestion uses the
# explicit document-only entry point; questions always go through embed_query.
contextual_chunks = document_chunks

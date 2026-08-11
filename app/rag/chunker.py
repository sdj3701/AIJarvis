"""Character-based document chunking with overlap."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextChunk:
    ordinal: int
    text: str
    start_char: int
    end_char: int


def chunk_text(text: str, *, chunk_chars: int, overlap_chars: int) -> tuple[TextChunk, ...]:
    if chunk_chars <= 0:
        raise ValueError("chunk_chars는 1 이상이어야 합니다")
    if overlap_chars < 0 or overlap_chars >= chunk_chars:
        raise ValueError("overlap_chars는 0 이상이고 chunk_chars보다 작아야 합니다")
    if not text:
        return ()

    chunks: list[TextChunk] = []
    start = 0
    ordinal = 0
    length = len(text)
    step = chunk_chars - overlap_chars
    while start < length:
        end = min(start + chunk_chars, length)
        chunks.append(
            TextChunk(
                ordinal=ordinal,
                text=text[start:end],
                start_char=start,
                end_char=end,
            )
        )
        if end >= length:
            break
        start += step
        ordinal += 1
    return tuple(chunks)

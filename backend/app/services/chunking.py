from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re


@dataclass(frozen=True)
class TextChunk:
    index: int
    text: str
    content_hash: str
    char_start: int
    char_end: int



def chunk_text(
    text: str,
    *,
    chunk_size: int = 600,
    overlap: int = 100,
) -> list[TextChunk]:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return []
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size must be positive and overlap must be smaller than chunk_size.")

    chunks: list[TextChunk] = []
    start = 0
    index = 0

    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        if end < len(cleaned):
            boundary = cleaned.rfind(" ", start, end)
            if boundary > start + chunk_size // 2:
                end = boundary

        segment = cleaned[start:end].strip()
        actual_start = cleaned.find(segment, start, end)
        actual_end = actual_start + len(segment)
        checksum = hashlib.sha256(segment.encode("utf-8")).hexdigest()

        chunks.append(
            TextChunk(
                index=index,
                text=segment,
                content_hash=checksum,
                char_start=actual_start,
                char_end=actual_end,
            )
        )
        index += 1

        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)

    return chunks

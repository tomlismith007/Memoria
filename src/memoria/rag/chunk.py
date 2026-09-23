"""Sliding-window chunker. Offsets double as citation locators (doc, chunk)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    index: int
    start: int  # char offset in the source document
    end: int


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[Chunk]:
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    chunks: list[Chunk] = []
    i, idx = 0, 0
    while i < len(text):
        end = min(i + size, len(text))
        chunks.append(Chunk(text=text[i:end], index=idx, start=i, end=end))
        if end == len(text):
            break
        i = end - overlap
        idx += 1
    return chunks

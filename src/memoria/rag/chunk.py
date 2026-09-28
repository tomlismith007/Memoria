"""Sliding-window chunker. Offsets double as citation locators (doc, chunk).

feat-051: cuts prefer sentence terminators and paragraph breaks over the raw
window edge, so a chunk rarely begins or ends mid-sentence. The cut *position*
moved; the offset contract did not — `chunk.text == source[chunk.start:chunk.end]`
still holds for every chunk, which is what the citation red line depends on.
"""

from __future__ import annotations

from dataclasses import dataclass

# Characters a cut may land on (inclusive of the char itself).
_TERMINATORS = "。！？!?；;：:\n"
_CLOSERS = "）」』】》\"')"  # a cut just before these is also clean


@dataclass
class Chunk:
    text: str
    index: int
    start: int  # char offset in the source document
    end: int


def _boundary_at_or_before(text: str, floor: int, ceiling: int) -> int:
    """Latest clean cut point in [floor, ceiling]; falls back to `ceiling`.

    A cut point is the index *after* the terminator, so the next chunk starts on
    fresh text. `floor` prevents pathological backtracking on long unpunctuated
    runs, `ceiling` keeps chunks from growing far past the requested size.
    """
    best = -1
    for i in range(min(ceiling, len(text) - 1), floor - 1, -1):
        if text[i] in _TERMINATORS:
            best = i + 1
            break
        if i + 1 < len(text) and text[i + 1] in _CLOSERS:
            best = i + 1
            break
    return best if best > floor else ceiling


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[Chunk]:
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    if not text:
        return []

    chunks: list[Chunk] = []
    start, idx = 0, 0
    # A boundary is only worth searching for in the back half of the window;
    # cutting earlier would produce chunks far below the requested size.
    search_floor = int(size * 0.5)

    while start < len(text):
        hard_end = min(start + size, len(text))
        if hard_end == len(text):
            end = hard_end  # tail chunk: the document simply ends here
        else:
            end = _boundary_at_or_before(text, start + search_floor, hard_end)
        chunks.append(Chunk(text=text[start:end], index=idx, start=start, end=end))
        if end == len(text):
            break
        # Step back by the overlap, but never past the start of this chunk.
        start = max(start + 1, end - overlap)
        idx += 1
    return chunks

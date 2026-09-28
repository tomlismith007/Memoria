"""feat-051: semantic-boundary chunking.

The invariant that must never break: `chunk.text == source[chunk.start:chunk.end]`.
Citation offsets are a red line (answers point back to exact character positions),
so boundary-aware cutting may only *choose where to cut*, never shift the offsets.

Before this change the chunker cut at a fixed window and sliced mid-sentence:
    '...需要提前 30 天发起续费'   <- ends mid-sentence
After it, cuts land on sentence terminators or paragraph breaks.
"""

import pytest

from memoria.rag import chunk_text

TERMINATORS = "。！？!?；;\n"


def test_offsets_always_address_the_source_exactly():
    """Red line: every chunk must slice back to itself from the source."""
    text = "服务 A 的订阅将于 2027 年到期。需要提前 30 天续费。逾期的罚则另有规定。" * 30
    for chunk in chunk_text(text, size=200, overlap=20):
        assert text[chunk.start : chunk.end] == chunk.text
        assert chunk.index >= 0 and chunk.start < chunk.end <= len(text)


def test_offsets_hold_for_every_parameter_combination():
    """The invariant is parameter-independent, not tuned for one size."""
    text = "第一句内容在这里。第二句稍微长一点点。第三句也不短。第四句结束。\n" * 20
    for size in (50, 80, 120, 200, 400):
        for overlap in (0, 10, 25):
            if overlap >= size:
                continue
            for chunk in chunk_text(text, size=size, overlap=overlap):
                assert text[chunk.start : chunk.end] == chunk.text, (size, overlap)


def test_chunks_end_on_a_boundary_when_one_is_available():
    """A cut inside a sentence is what we are fixing; this is the guard."""
    text = "服务 A 的订阅将于 2027 年 1 月 1 日到期。需要提前 30 天发起续费。逾期按月费 1.5 倍计费。"
    text = text * 30
    for chunk in chunk_text(text, size=120, overlap=15):
        body = chunk.text.rstrip()
        if body:  # the final chunk is allowed to end at EOF
            assert body[-1] in TERMINATORS or body[-1] in "）」』】", (
                f"chunk {chunk.index} ends mid-sentence: ...{body[-20:]!r}"
            )


def test_short_document_is_a_single_chunk():
    text = "很短的一句话。"
    chunks = chunk_text(text, size=800, overlap=100)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].start == 0
    assert chunks[0].end == len(text)


def test_content_is_fully_covered():
    """No gap: every character of the source belongs to some chunk."""
    text = "第一段内容。第二段内容！第三段内容？\n换行后的新段落继续说明。\n\n新章节开始了。" * 15
    chunks = chunk_text(text, size=100, overlap=15)
    covered = bytearray(len(text))
    for chunk in chunks:
        for i in range(chunk.start, chunk.end):
            covered[i] = 1
    assert all(covered), "some source characters are in no chunk"


def test_index_is_sequential_and_contiguous():
    text = "句子一。句子二。句子三。句子四。句子五。" * 20
    chunks = chunk_text(text, size=90, overlap=10)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    # Each chunk starts before the previous one ends (overlap) and moves forward.
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.start < prev.end, "chunks must overlap, not leave gaps"
        assert nxt.start > prev.start, "chunks must advance"


def test_overlap_still_shrinks():
    """feat-051 changes *where* we cut, not the offset contract.

    Chunk *count* is not the right thing to assert: with a long document the
    boundary search can absorb the overlap without adding a chunk. What must hold
    is the relation between consecutive offsets.
    """
    text = "短句。" + "中等长度的句子内容在这里。" * 30 + "短。" + "略长一些的句子。" * 20
    no_overlap = chunk_text(text, size=120, overlap=0)
    with_overlap = chunk_text(text, size=120, overlap=40)

    assert len(no_overlap) > 1 and len(with_overlap) > 1
    for prev, nxt in zip(no_overlap, no_overlap[1:]):
        assert nxt.start == prev.end  # no overlap -> chunks abut exactly
    for prev, nxt in zip(with_overlap, with_overlap[1:]):
        assert nxt.start < prev.end  # overlap -> chunks share text
        assert nxt.start > prev.start  # ...but still advance

    # Offsets address the source exactly in both modes.
    for mode in (no_overlap, with_overlap):
        for chunk in mode:
            assert text[chunk.start : chunk.end] == chunk.text


def test_overlap_at_or_above_size_is_rejected():
    with pytest.raises(ValueError):
        chunk_text("内容。" * 50, size=100, overlap=100)


def test_empty_text_yields_no_chunks():
    assert chunk_text("", size=100, overlap=10) == []


def test_text_without_terminators_still_chunks():
    """Degenerate input (no punctuation at all) must not loop forever."""
    text = "无标点的长文本" * 200
    chunks = chunk_text(text, size=100, overlap=10)
    assert chunks
    for chunk in chunks:
        assert text[chunk.start : chunk.end] == chunk.text

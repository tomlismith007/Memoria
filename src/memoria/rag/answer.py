"""Cited answering: retrieve -> prompt with numbered chunks -> LLM -> map [n] to sources."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from memoria.llm import ChatLLM
from memoria.rag.embed import Embedder
from memoria.rag.retrieve import retrieve
from memoria.rag.store import ChromaStore

SYSTEM = (
    "你是知识库问答助手。只根据下面提供的资料回答问题；"
    "每个回答句末尾用 [n] 标注来源编号（如 [1][2]）；"
    "资料不足以回答时，直接说无法回答，不要编造。"
)


@dataclass
class Citation:
    ref: int  # 1-based number as shown in the answer text
    doc_id: str
    chunk: int
    start: int


_CITE_RE = re.compile(r"\[(\d+)\]")
# Sentences end at CJK/latin terminators or newlines; trailing [n] markers
# belong to the preceding sentence (the prompt cites after the 句号).
_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;\n]*(?:\[\d+\])*")


def citations_complete(text: str, max_ref: int) -> bool:
    """Red line: every answer sentence must carry an in-range [n] reference."""
    return all(
        any(1 <= int(m) <= max_ref for m in _CITE_RE.findall(sentence))
        for sentence in _SENTENCE_RE.findall(text)
        if sentence.strip()
    )


@dataclass
class Answer:
    text: str
    citations: list[Citation] = field(default_factory=list)
    citations_verified: bool = True


def answer(
    question: str,
    store: ChromaStore,
    embedder: Embedder,
    llm: ChatLLM,
    k: int = 8,
    top_n: int = 4,
) -> Answer:
    hits = retrieve(question, store, embedder, k=k, top_n=top_n)
    if not hits:
        # Explicit refusal: no sources exist, so there is nothing to cite.
        return Answer(text="知识库中没有找到相关资料，无法回答。")
    context = "\n\n".join(f"[{i + 1}] {h['text']}" for i, h in enumerate(hits))
    text = llm.chat(SYSTEM, f"问题：{question}\n\n资料：\n{context}")
    refs = sorted({int(m) for m in _CITE_RE.findall(text) if 1 <= int(m) <= len(hits)})
    citations = [
        Citation(
            ref=r,
            doc_id=hits[r - 1]["doc_id"],
            chunk=hits[r - 1]["chunk"],
            start=hits[r - 1]["start"],
        )
        for r in refs
    ]
    return Answer(
        text=text,
        citations=citations,
        citations_verified=citations_complete(text, len(hits)),
    )

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


@dataclass
class Answer:
    text: str
    citations: list[Citation] = field(default_factory=list)


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
        return Answer(text="知识库中没有找到相关资料，无法回答。")
    context = "\n\n".join(f"[{i + 1}] {h['text']}" for i, h in enumerate(hits))
    text = llm.chat(SYSTEM, f"问题：{question}\n\n资料：\n{context}")
    refs = sorted(
        {int(m) for m in re.findall(r"\[(\d+)\]", text) if 1 <= int(m) <= len(hits)}
    )
    citations = [
        Citation(
            ref=r,
            doc_id=hits[r - 1]["doc_id"],
            chunk=hits[r - 1]["chunk"],
            start=hits[r - 1]["start"],
        )
        for r in refs
    ]
    return Answer(text=text, citations=citations)

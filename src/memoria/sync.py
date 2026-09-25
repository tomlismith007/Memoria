"""RAG x Wiki integration: dual-write ingest, wiki-first hybrid query, synthesis write-back."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from memoria.llm import ChatLLM
from memoria.rag import (
    Answer,
    ChromaStore,
    Citation,
    Embedder,
    answer as rag_answer,
    ingest_document,
)
from memoria.wiki import Wiki, WikiAnswer, ingest as wiki_ingest, query as wiki_query

GATE_SYSTEM = "你是回答质检员。判断 Wiki 回答是否充分回答了问题，只回 充分 或 补充，无多余解释。"


@dataclass
class DualResult:
    doc_id: str
    chunks: int
    wiki_pages: list[str]


def dual_ingest(
    source: str,
    store: ChromaStore,
    embedder: Embedder,
    wiki: Wiki,
    llm: ChatLLM,
) -> DualResult:
    """One document in, two pipelines: vectors for RAG + compiled pages for Wiki."""
    vec = ingest_document(source, store, embedder)  # parses once; text reused below
    pages = wiki_ingest(vec.text, source, wiki, llm)
    return DualResult(doc_id=vec.doc_id, chunks=vec.chunks, wiki_pages=pages)


@dataclass
class HybridAnswer:
    text: str
    source: str  # "wiki" | "rag+wiki"
    wiki_pages: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    citations_verified: bool = True


def hybrid_answer(
    question: str,
    wiki: Wiki,
    llm: ChatLLM,
    store: ChromaStore,
    embedder: Embedder,
) -> HybridAnswer:
    """Wiki first (precise, stable). LLM gate says 补充 -> vector retrieval fills details."""
    wans: WikiAnswer = wiki_query(question, wiki, llm)
    verdict = llm.chat(GATE_SYSTEM, f"问题：{question}\n\nWiki 回答：{wans.text}")
    if "补充" not in verdict and "充分" in verdict:
        return HybridAnswer(
            text=wans.text,
            source="wiki",
            wiki_pages=wans.pages,
            citations_verified=wans.citations_verified,
        )
    rans: Answer = rag_answer(question, store, embedder, llm)
    text = f"{wans.text}\n\n补充细节：\n{rans.text}"
    return HybridAnswer(
        text=text,
        source="rag+wiki",
        wiki_pages=wans.pages,
        citations=rans.citations,
        citations_verified=wans.citations_verified and rans.citations_verified,
    )


def _safe_name(question: str) -> str:
    slug = re.sub(r"[/\\?%*:|\"<>\n]", "-", question.strip())[:20] or "未命名"
    return f"问答归档-{date.today().isoformat()}-{slug}"


def archive_qa(
    question: str, answer_text: str, citations: list[Citation], wiki: Wiki
) -> str:
    """Write a high-quality Q&A back as a wiki synthesis page. No LLM call."""
    name = _safe_name(question)
    sources = "\n".join(f"- {c.doc_id}#{c.chunk}" for c in citations) or "- （无）"
    wiki.write_page(name, f"# {question}\n\n## 回答\n\n{answer_text}\n\n## 来源\n\n{sources}\n")
    wiki.build_index()
    wiki.append_log(f"归档问答 {name}")
    return name


def archive_fact(page: str, fact: str, origin: str, wiki: Wiki) -> bool:
    """Write an email-derived fact into a wiki page. Returns False if already present."""
    body = wiki.read_page(page) or f"# {page}\n"
    if fact in body:
        return False
    wiki.write_page(page, body + f"\n## 摘录\n\n- {fact}（来源：{origin}）\n")
    wiki.build_index()
    wiki.append_log(f"摘录事实入 [[{page}]]（{origin}）")
    return True

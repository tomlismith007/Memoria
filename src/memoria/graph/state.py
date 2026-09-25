"""Graph state. In-memory objects only; MemorySaver pickles them between steps."""

from __future__ import annotations

from typing import TypedDict

INTENTS = ("问答", "邮件", "ingest")


class MemoriaState(TypedDict, total=False):
    text: str  # raw user input
    intent: str  # 问答 | 邮件 | ingest; callers may preset it to skip the router LLM

    # QA branch (hybrid: wiki-first + rag fallback)
    answer_text: str
    answer_source: str  # "wiki" | "rag+wiki"
    answer_wiki_pages: list
    answer_citations: list
    answer_verified: bool
    history: list  # prior turns of this thread: [{"question": str, "answer": str}]

    # mail branch
    emails: list  # injected Email list (used when no live service)
    triages: list  # Triage objects
    pending_archive: list[str]
    confirmed_ids: list[str]
    archived: list[str]
    failed_ids: list[str]  # archive calls that raised on the Gmail side

    # ingest branch
    material: str  # text-only ingest (wiki compile, no vectors)
    source_path: str  # real file on disk (raw/): triggers dual write (vectors + wiki)
    origin: str
    doc_id: str
    chunks: int
    ingest_updated: list[str]
    lint_broken: list
    lint_orphans: list

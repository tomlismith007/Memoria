"""Graph state. In-memory objects only; MemorySaver pickles them between steps."""

from __future__ import annotations

from typing import TypedDict

INTENTS = ("问答", "邮件", "ingest")


class MemoriaState(TypedDict, total=False):
    text: str  # raw user input
    intent: str  # 问答 | 邮件 | ingest

    # QA branch
    answer_text: str
    answer_citations: list

    # mail branch
    emails: list  # injected Email list (used when no live service)
    triages: list  # Triage objects
    pending_archive: list[str]
    confirmed_ids: list[str]
    archived: list[str]

    # ingest branch (wiki-side multi-step; vector dual-write is feat-008)
    material: str
    origin: str
    ingest_updated: list[str]
    lint_broken: list
    lint_orphans: list

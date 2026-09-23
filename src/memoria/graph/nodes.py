"""Graph nodes: thin orchestration over rag / mail / wiki modules. No logic duplication."""

from __future__ import annotations

from langgraph.types import interrupt

from memoria.graph.state import INTENTS
from memoria.llm import ChatLLM
from memoria.mail import Email, archive, classify, fetch_messages, request_archive
from memoria.rag import ChromaStore, Embedder, answer as rag_answer
from memoria.wiki import Wiki, ingest as wiki_ingest, lint as wiki_lint

ROUTER_SYSTEM = "你是意图路由。只回一个词：问答、邮件、ingest，无多余解释。"


def make_router(llm: ChatLLM):
    def router(state: dict) -> dict:
        text = state.get("text", "")
        reply = llm.chat(ROUTER_SYSTEM, f"用户输入：{text}")
        for intent in INTENTS:
            if intent in reply:
                return {"intent": intent}
        return {"intent": "问答"}

    return router


def make_qa(store: ChromaStore, embedder: Embedder, llm: ChatLLM):
    def qa(state: dict) -> dict:
        ans = rag_answer(state.get("text", ""), store, embedder, llm)
        return {"answer_text": ans.text, "answer_citations": ans.citations}

    return qa


def make_mail_triage(llm: ChatLLM, service=None):
    def mail_triage(state: dict) -> dict:
        emails: list[Email] = list(state.get("emails", []))
        if service is not None:
            emails = fetch_messages(service)
        triages = [classify(e, llm) for e in emails]
        pending = [mid for t in triages if (mid := request_archive(t))]
        return {"triages": triages, "pending_archive": pending}

    return mail_triage


def confirm_archive(state: dict) -> dict:
    """Human-confirm node: pauses the graph until a person approves."""
    pending: list[str] = state.get("pending_archive", [])
    if not pending:
        return {"confirmed_ids": []}
    decision = interrupt({"pending_archive": pending})
    approved = [mid for mid in decision.get("approved", []) if mid in pending]
    return {"confirmed_ids": approved}


def make_mail_archive(service):
    def mail_archive(state: dict) -> dict:
        done = []
        for mid in state.get("confirmed_ids", []):
            archive(service, mid, confirmed=True)
            done.append(mid)
        return {"archived": done}

    return mail_archive


def make_ingest(wiki: Wiki, llm: ChatLLM):
    def ingest_node(state: dict) -> dict:
        # Multi-step ingest: read -> write pages -> rebuild index -> lint.
        updated = wiki_ingest(
            state.get("material", state.get("text", "")),
            state.get("origin", "graph"),
            wiki,
            llm,
        )
        report = wiki_lint(wiki)
        return {
            "ingest_updated": updated,
            "lint_broken": report.broken,
            "lint_orphans": report.orphans,
        }

    return ingest_node

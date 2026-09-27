"""Graph nodes: thin orchestration over sync / mail / wiki modules. No logic duplication."""

from __future__ import annotations

from langgraph.types import interrupt

from memoria.graph.state import INTENTS
from memoria.llm import ChatLLM
from memoria.mail import Email, archive, classify_batch, fetch_messages, request_archive
from memoria.rag import ChromaStore, Embedder
from memoria.sync import dual_ingest, hybrid_answer
from memoria.wiki import Wiki, ingest as wiki_ingest, lint as wiki_lint

ROUTER_SYSTEM = "你是意图路由。只回一个词：问答、邮件、ingest，无多余解释。"

# ponytail: character estimate, not a real tokenizer. 1.5 chars/token is the CJK
# side (English would allow ~4), so this errs toward keeping fewer turns than a
# tokenizer would. Upgrade path: swap in tiktoken if a turn ever needs exact
# budgeting against a model-reported context window.
KEEP_RECENT_TOKENS = 20_000
_CHARS_PER_TOKEN = 1.5


def _recent_turns(history: list, budget: int = KEEP_RECENT_TOKENS) -> list:
    """Newest turns that fit the token budget; the oldest are dropped first."""
    kept: list = []
    used = 0.0
    for turn in reversed(history):
        cost = (len(turn.get("question", "")) + len(turn.get("answer", ""))) / _CHARS_PER_TOKEN
        if used + cost > budget and kept:
            break
        kept.append(turn)
        used += cost
    kept.reverse()
    return kept


def make_router(llm: ChatLLM):
    def router(state: dict) -> dict:
        preset = state.get("intent")
        if preset in INTENTS:
            # Structured endpoints (/api/ask, /api/ingest, /api/mail) already state
            # their intent in the URL, so re-asking the model would be a wasted
            # round-trip. /api/agent omits `intent` and is the path that pays for
            # the LLM call below — that keeps the conditional edges exercised in
            # production rather than only in tests.
            return {}
        text = state.get("text", "")
        reply = llm.chat(ROUTER_SYSTEM, f"用户输入：{text}")
        for intent in INTENTS:
            if intent in reply:
                return {"intent": intent}
        return {"intent": "问答"}

    return router


def make_qa(store: ChromaStore, embedder: Embedder, llm: ChatLLM, wiki: Wiki):
    def qa(state: dict) -> dict:
        question = state.get("text", "")
        # Follow-up turns ride along as a transcript so 指代 ("那它呢") resolves;
        # the transcript lives in the user message, so every backend/fake stays single-turn.
        turns = _recent_turns(state.get("history", []))
        transcript = "\n\n".join(
            f"用户：{t['question']}\n助手：{t['answer']}" for t in turns
        )
        if transcript:
            question = f"（此前对话）\n{transcript}\n\n（本次问题）\n{question}"
        ans = hybrid_answer(question, wiki, llm, store, embedder)
        return {
            "answer_text": ans.text,
            "answer_source": ans.source,
            "answer_wiki_pages": ans.wiki_pages,
            "answer_citations": ans.citations,
            "answer_verified": ans.citations_verified,
            "history": turns + [{"question": state.get("text", ""), "answer": ans.text}],
        }

    return qa


def make_mail_triage(llm: ChatLLM, service=None):
    def mail_triage(state: dict) -> dict:
        emails: list[Email] = list(state.get("emails", []))
        if service is not None:
            emails = fetch_messages(service)
        triages = classify_batch(emails, llm)
        pending = [mid for t in triages if (mid := request_archive(t))]
        return {"triages": triages, "pending_archive": pending}

    return mail_triage


def confirm_archive(state: dict) -> dict:
    """Human-confirm node: pauses the graph until a person approves."""
    pending: list[str] = state.get("pending_archive", [])
    if not pending:
        return {"confirmed_ids": []}
    decision = interrupt({"pending_archive": pending})
    triages = {t.email.msg_id: t for t in state.get("triages", [])}
    approved = []
    for mid in decision.get("approved", []):
        t = triages.get(mid)
        # Belt and braces on the red line: only pending, non-protected mail passes.
        if mid in pending and t is not None and not t.protected:
            approved.append(mid)
    return {"confirmed_ids": approved}


def make_mail_archive(service):
    def mail_archive(state: dict) -> dict:
        done: list[str] = []
        failed: list[str] = []
        for mid in state.get("confirmed_ids", []):
            if service is None:
                done.append(mid)  # offline mode: confirmation recorded, no Gmail call
                continue
            try:
                archive(service, mid, confirmed=True)
                done.append(mid)
            except Exception:
                failed.append(mid)
        return {"archived": done, "failed_ids": failed}

    return mail_archive


def make_ingest(store: ChromaStore, embedder: Embedder, wiki: Wiki, llm: ChatLLM):
    def ingest_node(state: dict) -> dict:
        # source_path (real raw/ file) -> dual write: vectors + wiki pages.
        # Plain material text -> wiki-only compile; the agent never writes raw/.
        source_path = state.get("source_path")
        origin = state.get("origin", "graph")
        update: dict = {}
        if source_path:
            res = dual_ingest(source_path, store, embedder, wiki, llm)
            update["doc_id"] = res.doc_id
            update["chunks"] = res.chunks
            updated = res.wiki_pages
        else:
            updated = wiki_ingest(
                state.get("material", state.get("text", "")), origin, wiki, llm
            )
        report = wiki_lint(wiki)
        update.update(
            {
                "ingest_updated": updated,
                "lint_broken": report.broken,
                "lint_orphans": report.orphans,
            }
        )
        return update

    return ingest_node

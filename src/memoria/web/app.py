"""FastAPI application providing Web APIs for Memoria.

Serves RAG hybrid search, Wiki explorer, Mail triage, and dual-ingest pipelines.
Supports dependency injection for 100% offline, deterministic testing.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import BaseModel, Field

from memoria.graph import build_graph
from memoria.llm import ChatLLM, OpenAICompatibleChat
from memoria.mail import Email, fetch_messages
from memoria.mail.auth import get_gmail_service
from memoria.proposals import (
    ProposalError,
    ProposalInvalid,
    ProposalService,
)
from memoria.rag import (
    ChromaStore,
    Citation,
    OpenAICompatibleEmbedder,
    doc_id_for_origin,
    ingest_document,
)
from memoria.records import RecordStore
from memoria.sync import archive_qa, archive_fact
from memoria.tasks import TaskEngine, notify
from memoria.web.config import (
    MAIL_NOT_CONNECTED_HINT,
    Settings,
    capability_status,
    load_settings,
    resolve_active_chat_model,
)
from memoria.web.config_routes import register_config_routes
from memoria.wiki import Wiki, extract_links, lint as wiki_lint


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    conversation_id: str = ""  # empty -> new conversation thread (its id is returned)


class AgentRequest(BaseModel):
    text: str = Field(..., min_length=1)
    conversation_id: str = ""
    # Force a branch instead of paying for the router LLM call. Empty = let the
    # graph's router node decide, which is the point of this endpoint.
    intent: str = ""


class ArchiveQARequest(BaseModel):
    question: str
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)


class MailArchiveRequest(BaseModel):
    confirmed_ids: list[str]
    thread_id: str = ""  # triage session; the graph interrupt lives on this thread


class ProposalCreateRequest(BaseModel):
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ProposalDecideRequest(BaseModel):
    decision: str  # "approved" | "denied"
    content_hash: str  # must echo the hash shown at review time (anti-swap)


class MailFactRequest(BaseModel):
    msg_id: str
    page: str
    fact: str = Field(..., min_length=1)


class IngestTextRequest(BaseModel):
    text: str
    origin: str = "web_input.md"


def _safe_raw_path(raw_dir: Path, name: str) -> Path:
    path = Path(name)
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or "\x00" in name
        or path.is_absolute()
        or path.name != name
    ):
        raise HTTPException(status_code=400, detail="Invalid raw filename")
    root = raw_dir.resolve()
    candidate = (root / name).resolve()
    if candidate.parent != root:
        raise HTTPException(status_code=400, detail="Invalid raw filename")
    return candidate


def create_app(overrides: dict[str, Any] | None = None) -> FastAPI:
    app = FastAPI(title="Memoria Web API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    overrides = overrides or {}
    chroma_path = overrides.get("chroma_path") or os.environ.get("MEMORIA_CHROMA", "./data/chroma")
    wiki_path = overrides.get("wiki_path") or os.environ.get("MEMORIA_WIKI", "./data/wiki")

    store = overrides.get("store") or ChromaStore(path=chroma_path)
    embedder = overrides.get("embedder") or OpenAICompatibleEmbedder()
    llm: ChatLLM = overrides.get("llm") or OpenAICompatibleChat()
    wiki: Wiki = overrides.get("wiki") or Wiki(wiki_path)
    wiki.ensure_layout()
    mail_service = overrides.get("mail_service")
    # feat-069: production mail wiring. Injected services (tests) are ready by
    # construction; otherwise build non-interactively from data/token.json —
    # startup must never pop a browser OAuth flow, so any failure degrades to
    # a capability reason instead of blocking boot.
    if "mail_service" in overrides:
        mail_status: dict[str, Any] = {
            "ready": mail_service is not None,
            "reason": "" if mail_service is not None else "邮件服务已注入为 None（测试/离线模式）",
        }
    else:
        token_path = os.environ.get("MEMORIA_GMAIL_TOKEN", "./data/token.json")
        if not Path(token_path).exists():
            mail_service = None
            mail_status = {"ready": False, "reason": MAIL_NOT_CONNECTED_HINT}
        else:
            try:
                mail_service = get_gmail_service(token_path=token_path, interactive=False)
                mail_status = {"ready": True, "reason": ""}
            except Exception as e:
                mail_service = None
                mail_status = {"ready": False, "reason": f"Gmail 连接失败：{str(e)[:200]}"}
    cached_emails: list[Email] = overrides.get("emails", [])

    # feat-066: single-table record store; proposals live here (tasks/memories later).
    records_path = overrides.get("records_path") or os.environ.get(
        "MEMORIA_RECORDS", "./data/memoria.db"
    )
    record_store = overrides.get("records") or RecordStore(records_path)
    proposals = overrides.get("proposals") or ProposalService(record_store)
    # A restart during execution leaves the result unknowable: mark it, never fake it.
    proposals.recover_interrupted()

    checkpointer = overrides.get("checkpointer")
    if checkpointer is None:
        checkpoint_db = overrides.get("checkpoint_db") or os.environ.get(
            "MEMORIA_CHECKPOINT_DB", "./data/checkpoints.sqlite"
        )
        checkpointer = SqliteSaver(
            sqlite3.connect(checkpoint_db, check_same_thread=False),
            serde=JsonPlusSerializer(
                allowed_msgpack_modules=[
                    ("memoria.mail.classify", "Email"),
                    ("memoria.mail.classify", "Triage"),
                ]
            ),
        )

    def build_compiled():
        return build_graph(
            store, embedder, llm, wiki, mail_service, proposals=proposals
        ).compile(checkpointer=checkpointer)

    compiled_graph = build_compiled()

    # feat-047: tracked so /api/health can report real readiness. Loaded once at
    # startup because the config routes only read settings on demand, which left
    # the health check blind to a missing embedding config.
    current_settings: Settings | None = None
    if "llm" not in overrides or "embedder" not in overrides:
        try:
            current_settings = load_settings()
        except Exception:
            current_settings = None  # unreadable settings: fall back to live probes

    def activate_settings(settings: Settings) -> None:
        nonlocal llm, embedder, compiled_graph, current_settings
        current_settings = settings
        if settings.demo_mode:
            from memoria.llm import FakeChat
            from memoria.rag import FakeEmbedder

            llm = FakeChat()
            embedder = FakeEmbedder()
            compiled_graph = build_compiled()
            return
        llm_base_url = settings.llm_base_url
        llm_api_key = settings.llm_api_key
        llm_model = settings.llm_model

        active_provider = next(
            (p for p in settings.providers if p.id == settings.active_provider_id),
            None,
        )
        if active_provider and active_provider.enabled:
            llm_base_url = active_provider.base_url
            if active_provider.api_key:
                llm_api_key = active_provider.api_key
            llm_model = resolve_active_chat_model(settings) or llm_model

        if "llm" not in overrides:
            llm = OpenAICompatibleChat(
                base_url=llm_base_url,
                api_key=llm_api_key or "no-key",
                model=llm_model,
                api_format=active_provider.api_format if active_provider else None,
            )

        embed_base_url = settings.embed_base_url
        embed_api_key = settings.embed_api_key
        embed_model = settings.embed_model

        embed_provider = next(
            (p for p in settings.providers if p.id == settings.active_embed_provider_id),
            None,
        )
        if embed_provider and embed_provider.enabled and settings.active_embed_model:
            embed_base_url = embed_provider.base_url
            if embed_provider.api_key:
                embed_api_key = embed_provider.api_key
            embed_model = settings.active_embed_model
        elif settings.active_embed_model and active_provider and active_provider.enabled:
            # Legacy settings stored only an embedding model under the active chat provider.
            embed_base_url = active_provider.base_url
            if active_provider.api_key:
                embed_api_key = active_provider.api_key
            embed_model = settings.active_embed_model

        if "embedder" not in overrides:
            embedder = OpenAICompatibleEmbedder(
                base_url=embed_base_url,
                api_key=embed_api_key or "no-key",
                model=embed_model,
            )
        compiled_graph = build_compiled()

    # feat-068: minimal durable task engine. Only starts when Gmail is actually
    # ready (a not-connected run would just spam failure notifications); env
    # kill switch MEMORIA_TASKS=0. Tests inject `task_engine` explicitly.
    task_engine = overrides.get("task_engine")
    if task_engine is None and mail_status["ready"] and os.environ.get("MEMORIA_TASKS", "1") != "0":
        interval = int(os.environ.get("MEMORIA_MAIL_TRIAGE_INTERVAL", "1800"))

        def mail_triage_handler(task: dict) -> dict:
            # Reads the CURRENT compiled graph (activate_settings may rebuild it).
            thread_id = uuid.uuid4().hex
            emails = fetch_messages(mail_service)
            result = compiled_graph.invoke(
                {"intent": "邮件", "emails": emails},
                {"configurable": {"thread_id": thread_id}},
            )
            candidates = [t for t in result.get("triages", []) if t.archive_candidate]
            if not candidates:
                return {"pending": 0}
            pending_ids = [t.email.msg_id for t in candidates]
            digest = hashlib.sha256(",".join(sorted(pending_ids)).encode("utf-8")).hexdigest()[:16]
            payload = {
                "thread_id": thread_id,
                "confirmed_ids": pending_ids,
                "msgs": [
                    {
                        "msg_id": t.email.msg_id,
                        "subject": t.email.subject,
                        "sender": t.email.sender,
                        "category": t.category,
                    }
                    for t in candidates
                ],
            }
            # Idempotent replay: the same mail set maps to the same idem key, so a
            # re-claimed task (crash mid-run) never duplicates a proposal.
            proposal = proposals.propose(
                "archive", payload, idem_key=f"archive:auto:{digest}"
            )
            notify(
                record_store,
                f"proposal-ready:{digest}",
                "邮件归档提案待审",
                f"{len(candidates)} 封营销邮件等待批准（30 分钟内有效）。",
                link=proposal["id"],
            )
            return {"pending": len(candidates), "proposal_id": proposal["id"]}

        task_engine = TaskEngine(record_store, {"mail_triage": mail_triage_handler})
        task_engine.ensure_task("mail_triage", interval_seconds=interval)
        task_engine.start()
        # add_event_handler was removed from newer FastAPI; the router's
        # on_shutdown list is the supported equivalent.
        app.router.on_shutdown.append(task_engine.stop)

    register_config_routes(app, activate_settings=activate_settings)

    # feat-061: Cold start bootstrap - activate loaded settings immediately
    if current_settings is not None:
        activate_settings(current_settings)

    def _require(capability: str) -> None:
        """feat-048/feat-061: fail with an instruction, not a socket timeout.

        Only intercepts a genuinely missing config. Injected deps (tests) and demo
        mode are ready by construction; every other error keeps its original path.
        """
        if current_settings is None or current_settings.demo_mode:
            return
        if capability == "embed" and "embedder" in overrides:
            return
        if capability == "llm" and "llm" in overrides:
            return
        caps = capability_status(current_settings)
        if not caps[capability]["ready"]:
            raise HTTPException(status_code=502, detail=caps[capability]["reason"])

    @app.get("/api/health")
    def health():
        # feat-047: process liveness was reported as "ok" even when the embedding
        # config was missing and every ask/ingest call failed with a socket timeout.
        body: dict[str, Any] = {"status": "ok", "version": "0.1.0"}
        # feat-069: mail readiness rides on the app-level service, not settings.
        mail_caps = {
            "ready": bool(mail_status["ready"]),
            "reason": mail_status["reason"],
            "model": "gmail",
        }
        if current_settings is None:
            body["capabilities"] = {
                "llm": {"ready": True, "model": "injected", "reason": ""},
                "embed": {"ready": True, "model": "injected", "reason": ""},
                "mail": mail_caps,
            }
        else:
            caps = dict(capability_status(current_settings))
            caps["mail"] = mail_caps
            body["capabilities"] = caps
        return body

    @app.post("/api/ask")
    def api_ask(req: AskRequest):
        # conversation_id is the LangGraph thread: the checkpointer replays the
        # prior turns (feat-034) and survives restarts via SqliteSaver.
        _require("llm")
        _require("embed")
        conversation_id = req.conversation_id or uuid.uuid4().hex
        config = {"configurable": {"thread_id": conversation_id}}
        try:
            result = compiled_graph.invoke(
                {"text": req.question, "intent": "问答"}, config
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"LLM 接口调用失败: {str(e)[:180]}")
        return {
            "text": result["answer_text"],
            "conversation_id": conversation_id,
            "source": result.get("answer_source", "rag+wiki"),
            "wiki_pages": result.get("answer_wiki_pages", []),
            "citations_verified": result.get("answer_verified", False),
            "citations": [
                {
                    "ref": c.ref,
                    "doc_id": c.doc_id,
                    "chunk": c.chunk,
                    "start": c.start,
                }
                for c in result.get("answer_citations", [])
            ],
        }

    @app.post("/api/agent")
    def api_agent(req: AgentRequest):
        """Free-text entry point: the graph's router node decides the branch.

        The other endpoints preset `intent` because their URL already states it
        (/api/ask is a question, /api/ingest is a document). This one does not, so it
        is the path that actually exercises LangGraph's conditional edges in
        production — the routing the graph was built for.
        """
        conversation_id = req.conversation_id or uuid.uuid4().hex
        config = {"configurable": {"thread_id": conversation_id}}
        _require("llm")
        if not req.intent or req.intent == "问答":
            _require("embed")  # only the qa branch reaches the vector store
        payload: dict[str, Any] = {"text": req.text}
        if req.intent:
            payload["intent"] = req.intent
        try:
            result = compiled_graph.invoke(payload, config)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Agent 调用失败: {str(e)[:180]}")

        intent = result.get("intent", "问答")
        response: dict[str, Any] = {
            "intent": intent,
            "conversation_id": conversation_id,
        }
        if intent == "问答":
            response.update(
                {
                    "text": result.get("answer_text", ""),
                    "source": result.get("answer_source", "rag+wiki"),
                    "wiki_pages": result.get("answer_wiki_pages", []),
                    "citations_verified": result.get("answer_verified", False),
                    "citations": [
                        {"ref": c.ref, "doc_id": c.doc_id, "chunk": c.chunk, "start": c.start}
                        for c in result.get("answer_citations", [])
                    ],
                }
            )
        elif intent == "ingest":
            response.update(
                {
                    "doc_id": result.get("doc_id"),
                    "chunks": result.get("chunks", 0),
                    "wiki_pages": result.get("ingest_updated", []),
                }
            )
        elif intent == "邮件":
            # Triage stops at the human-confirmation interrupt, so nothing is
            # archived here. The caller must POST /api/mail/archive with this id.
            response["thread_id"] = conversation_id
            response["pending_archive"] = result.get("pending_archive", [])
            response["message"] = "邮件分拣已暂停，等待人工确认。"
        return response

    @app.get("/api/wiki/pages")
    def api_wiki_pages(deep: bool = False):
        # deep=true adds the LLM contradiction check (costs one call per linked pair).
        pages = wiki.list_pages()
        report = wiki_lint(wiki, llm=llm if deep else None)
        details = []
        for p in pages:
            body = wiki.read_page(p) or ""
            links = extract_links(body)
            details.append({"name": p, "links": links, "length": len(body)})
        return {
            "pages": details,
            "lint": {
                "broken": report.broken,
                "orphans": report.orphans,
                "contradictions": report.contradictions,
            },
        }

    @app.get("/api/wiki/page/{name}")
    def api_wiki_page(name: str):
        content = wiki.read_page(name)
        if content is None:
            raise HTTPException(status_code=404, detail=f"Page {name} not found")
        links = extract_links(content)
        # Compute backlinks from other pages
        backlinks: list[str] = []
        for other in wiki.list_pages():
            if other != name:
                other_text = wiki.read_page(other) or ""
                if name in extract_links(other_text):
                    backlinks.append(other)
        return {
            "name": name,
            "content": content,
            "links": sorted(links),
            "backlinks": sorted(backlinks),
        }

    @app.post("/api/wiki/archive-qa")
    def api_archive_qa(req: ArchiveQARequest):
        citations = [
            Citation(
                ref=c.get("ref", i + 1),
                doc_id=c.get("doc_id", "unknown"),
                chunk=c.get("chunk", 0),
                start=c.get("start", 0),
            )
            for i, c in enumerate(req.citations)
        ]
        page_name = archive_qa(req.question, req.answer, citations, wiki)
        return {"name": page_name, "message": f"Successfully archived as [[{page_name}]]"}

    @app.get("/api/mail/triage")
    def api_mail_triage():
        thread_id = uuid.uuid4().hex
        config = {"configurable": {"thread_id": thread_id}}
        try:
            result = compiled_graph.invoke(
                {"intent": "邮件", "emails": list(cached_emails)}, config
            )
        except Exception as e:
            return {"triages": [], "thread_id": thread_id, "pending": [], "error": str(e)}

        triages = result.get("triages", [])
        return {
            "thread_id": thread_id,
            # feat-069: the UI distinguishes "no mail to triage" from "Gmail
            # not connected / connection broken".
            "mail_ready": bool(mail_status["ready"]),
            "mail_reason": mail_status["reason"],
            "pending": [t.email.msg_id for t in triages if t.archive_candidate],
            "triages": [
                {
                    "id": t.email.msg_id,
                    "msg_id": t.email.msg_id,
                    "subject": t.email.subject,
                    "sender": t.email.sender,
                    "snippet": t.email.snippet,
                    "category": t.category,
                    "summary": t.summary,
                    "protected": t.protected,
                    "can_archive": t.archive_candidate,
                }
                for t in triages
            ],
        }

    @app.post("/api/mail/archive")
    def api_mail_archive(req: MailArchiveRequest):
        """feat-066: creates a hash-bound archive proposal instead of resuming.

        Execution happens ONLY through POST /api/proposals/{id}/decide → the
        decide path resumes this graph thread with the decision; the confirm node
        still whitelists ids against pending/non-protected (red line, depth 2) and
        the mail_archive node writes the proposal's terminal status. The chat path
        has no route to any of this.
        """
        if not req.thread_id:
            raise HTTPException(status_code=400, detail="thread_id is required")
        config = {"configurable": {"thread_id": req.thread_id}}
        snapshot = compiled_graph.get_state(config)
        if not any(t.interrupts for t in snapshot.tasks):
            return {
                "proposal": None,
                "blocked": list(req.confirmed_ids),
                "message": "No pending confirmation on this triage session.",
            }
        values = snapshot.values or {}
        pending = set(values.get("pending_archive", []))
        triages = {t.email.msg_id: t for t in values.get("triages", [])}
        valid: list[str] = []
        for mid in req.confirmed_ids:
            t = triages.get(mid)
            # Same whitelist the confirm node enforces; kept here so the proposal
            # payload only ever describes executable mail (hash binds to it).
            if mid in pending and t is not None and not t.protected and t.archive_candidate:
                valid.append(mid)
        blocked = [mid for mid in req.confirmed_ids if mid not in valid]
        if not valid:
            return {
                "proposal": None,
                "blocked": blocked,
                "message": "无可归档候选（受保护邮件永不归档，非候选邮件需先通过分拣）。",
            }
        payload = {
            "thread_id": req.thread_id,
            "confirmed_ids": valid,
            "msgs": [
                {
                    "msg_id": mid,
                    "subject": triages[mid].email.subject,
                    "sender": triages[mid].email.sender,
                    "category": triages[mid].category,
                }
                for mid in valid
            ],
        }
        proposal = proposals.propose("archive", payload, idem_key=f"archive:{req.thread_id}")
        return {
            "proposal": proposal,
            "blocked": blocked,
            "message": "已创建归档提案，等待批准（30 分钟内有效）。",
        }

    @app.get("/api/proposals")
    def api_list_proposals(status: str | None = None):
        return {"proposals": proposals.list(status=status)}

    @app.post("/api/proposals")
    def api_create_proposal(req: ProposalCreateRequest):
        """Client-initiated destructive actions (delete_doc / reindex). Archive
        proposals are created only by the mail flow (see api_mail_archive)."""
        if req.kind == "archive":
            raise HTTPException(status_code=400, detail="归档提案只能由邮件分拣流程创建")
        if req.kind == "delete_doc":
            doc_id = str(req.payload.get("doc_id", ""))
            raw_target = _find_raw_target(doc_id)
            if raw_target is None and doc_id not in store.documents():
                raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
            payload = {"doc_id": doc_id, "name": raw_target.name if raw_target else None}
            idem_key = f"delete_doc:{doc_id}"
        elif req.kind == "reindex":
            _require("embed")  # fail at propose time, not at decide time
            payload = {"raw_files": len([f for f in wiki.raw_dir.iterdir() if f.is_file()])}
            idem_key = "reindex"
        else:
            raise HTTPException(status_code=400, detail=f"未知的提案类型: {req.kind}")
        proposal = proposals.propose(req.kind, payload, idem_key=idem_key)
        return {"proposal": proposal}

    @app.post("/api/proposals/{proposal_id}/decide")
    def api_decide_proposal(proposal_id: str, req: ProposalDecideRequest):
        """The ONLY approval path in the system. Hash-bound, expiring, single
        claim; then executes by kind. Chat/agent endpoints cannot reach here."""
        try:
            p = proposals.decide(proposal_id, req.decision, req.content_hash)
        except ProposalError as e:
            raise HTTPException(status_code=e.status_code, detail=str(e))
        if p["status"] != "executing":  # denied, or an idempotent replay of a terminal record
            return {"proposal": p}
        try:
            if p["kind"] == "archive":
                payload = p["payload"]
                _resume_archive_thread(payload["thread_id"], proposal_id, payload["confirmed_ids"])
                # The mail_archive node wrote the terminal status (its receipt).
                final = proposals.get(proposal_id) or p
                return {"proposal": final}
            if p["kind"] == "delete_doc":
                result = _execute_delete_doc(p["payload"]["doc_id"])
            elif p["kind"] == "reindex":
                result = _execute_reindex()
            else:  # defensive: kinds are validated at propose time
                raise ProposalInvalid(f"未知的提案类型: {p['kind']}")
        except ProposalInvalid as e:
            proposals.complete(proposal_id, "failed", error=str(e))
            raise HTTPException(status_code=e.status_code, detail=str(e))
        except Exception as e:
            proposals.complete(proposal_id, "failed", error=str(e)[:160])
            raise HTTPException(status_code=502, detail=f"提案执行失败: {str(e)[:160]}")
        return {"proposal": proposals.complete(proposal_id, "succeeded", result=result)}

    @app.get("/api/tasks")
    def api_tasks():
        """feat-068: scheduled task status (kind, next run, attempts, last error)."""
        return {"tasks": task_engine.list_tasks() if task_engine else []}

    @app.get("/api/notifications")
    def api_notifications(unread: bool = False):
        """feat-068: append-only notification inbox — mark-read only, no delete."""
        return {
            "notifications": task_engine.list_notifications(unread_only=unread) if task_engine else []
        }

    @app.post("/api/notifications/{notification_id}/read")
    def api_notification_read(notification_id: str):
        if task_engine is None:
            raise HTTPException(status_code=404, detail="通知收件箱未启用")
        n = task_engine.mark_notification_read(notification_id)
        if n is None:
            raise HTTPException(status_code=404, detail="通知不存在或已读")
        return {"notification": n}

    def _find_raw_target(doc_id: str) -> Path | None:
        for f in wiki.raw_dir.iterdir():
            if f.is_file() and doc_id_for_origin(str(f.resolve())) == doc_id:
                return f
        return None

    def _resume_archive_thread(thread_id: str, proposal_id: str, confirmed_ids: list[str]) -> dict:
        """Server-side only: resumes the parked triage thread with the decision.
        Returns the graph's archived/blocked summary; the mail_archive node owns
        the proposal's terminal status."""
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = compiled_graph.get_state(config)
        if not any(t.interrupts for t in snapshot.tasks):
            return {"archived": [], "blocked": list(confirmed_ids)}
        result = compiled_graph.invoke(
            Command(
                resume={
                    "decision": "approved",
                    "proposal_id": proposal_id,
                    "approved": list(confirmed_ids),
                }
            ),
            config,
        )
        archived = list(result.get("archived", []))
        return {"archived": archived, "blocked": [m for m in confirmed_ids if m not in archived]}

    @app.get("/api/documents")
    def api_documents():
        vector_docs = store.documents()
        documents = []
        for f in sorted(wiki.raw_dir.iterdir()):
            if not f.is_file():
                continue
            doc_id = doc_id_for_origin(str(f.resolve()))
            documents.append({
                "doc_id": doc_id,
                "name": f.name,
                "size": f.stat().st_size,
                "chunks": vector_docs.pop(doc_id, 0),  # 0 = uploaded but not yet ingested
            })
        # Vectors whose raw source is a URL or was already removed from raw/.
        vector_only = [
            {"doc_id": doc_id, "chunks": chunks} for doc_id, chunks in sorted(vector_docs.items())
        ]
        return {"documents": documents, "vector_only": vector_only}

    def _execute_delete_doc(doc_id: str) -> dict:
        """Red line: deletion removes the doc's raw file AND all of its vectors.
        Runs only under an approved delete_doc proposal (feat-066)."""
        raw_target = _find_raw_target(doc_id)
        if raw_target is None and doc_id not in store.documents():
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
        store.delete_document(doc_id)
        if doc_id in store.documents():  # paranoia guard on the red line
            raise HTTPException(status_code=500, detail="Orphan vectors remain after deletion")
        raw_name = raw_target.name if raw_target else None
        if raw_target is not None:
            raw_target.unlink()  # source came from raw_dir iteration, so path-safe
        wiki.append_log(f"删除文档 {doc_id}：全部向量与 raw 文件（{raw_name or '无'}）已清除（经提案批准）")
        return {"deleted": doc_id, "raw_removed": raw_name}

    def _execute_reindex() -> dict:
        """Rebuilds the vector index from all files in data/raw. Necessary when
        switching embedding models with differing dimensions. Runs only under an
        approved reindex proposal (feat-066)."""
        if hasattr(store, "reset_collection"):
            store.reset_collection()
        raw_files = [f for f in sorted(wiki.raw_dir.iterdir()) if f.is_file()]
        reindexed = []
        total_chunks = 0
        for f in raw_files:
            try:
                res = ingest_document(str(f.resolve()), store, embedder)
                total_chunks += res.chunks
                reindexed.append({
                    "name": f.name,
                    "doc_id": res.doc_id,
                    "chunks": res.chunks,
                })
            except Exception as e:
                reindexed.append({
                    "name": f.name,
                    "error": str(e)[:120],
                })
        wiki.append_log(
            f"重建向量索引：清空旧集合，重新摄入 {len([r for r in reindexed if 'chunks' in r])} 篇原始文档（共 {total_chunks} 个切片）（经提案批准）"
        )
        return {
            "status": "ok",
            "documents_reindexed": len([r for r in reindexed if "chunks" in r]),
            "total_chunks": total_chunks,
            "documents": reindexed,
        }

    @app.post("/api/mail/fact")
    def api_mail_fact(req: MailFactRequest):
        """Writes an email-derived fact into a wiki page (compounding loop, feat-008)."""
        page = req.page.strip()
        fact = req.fact.strip()
        if not page or "/" in page or "\\" in page or ".." in page:
            raise HTTPException(status_code=400, detail="Invalid wiki page name")
        if not fact:
            raise HTTPException(status_code=400, detail="Fact must not be empty")
        added = archive_fact(page, fact, f"mail:{req.msg_id}", wiki)
        return {
            "page": page,
            "added": added,
            "message": (
                f"已摘录进 [[{page}]]" if added else f"[[{page}]] 已存在相同摘录，未重复写入"
            ),
        }

    def run_ingest(source_path: Path, origin: str) -> dict:
        _require("embed")
        config = {"configurable": {"thread_id": uuid.uuid4().hex}}
        try:
            result = compiled_graph.invoke(
                {"intent": "ingest", "source_path": str(source_path), "origin": origin},
                config,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"摄入失败: {str(e)[:180]}")
        return {
            "doc_id": result.get("doc_id"),
            "chunks": result.get("chunks", 0),
            "wiki_pages": result.get("ingest_updated", []),
            "origin": origin,
        }

    @app.post("/api/ingest")
    def api_ingest(req: IngestTextRequest):
        # User inputs are written once; LLM/agent compilation treats raw/ as read-only.
        temp_source = _safe_raw_path(wiki.raw_dir, req.origin)
        temp_source.write_text(req.text, encoding="utf-8")
        return run_ingest(temp_source, req.origin)

    @app.post("/api/ingest/file")
    async def api_ingest_file(file: UploadFile = File(...)):
        target_path = _safe_raw_path(wiki.raw_dir, file.filename or "")
        content = await file.read()
        target_path.write_bytes(content)
        response = run_ingest(target_path, file.filename or "")
        response["filename"] = file.filename
        return response

    # Mount frontend static files if built
    frontend_dist = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()

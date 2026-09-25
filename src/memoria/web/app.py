"""FastAPI application providing Web APIs for Memoria.

Serves RAG hybrid search, Wiki explorer, Mail triage, and dual-ingest pipelines.
Supports dependency injection for 100% offline, deterministic testing.
"""

from __future__ import annotations

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
from memoria.mail import Email, request_archive
from memoria.rag import ChromaStore, Citation, OpenAICompatibleEmbedder, doc_id_for_origin
from memoria.sync import archive_qa, archive_fact
from memoria.web.config import Settings
from memoria.web.config_routes import register_config_routes
from memoria.wiki import Wiki, extract_links, lint as wiki_lint


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    conversation_id: str = ""  # empty -> new conversation thread (its id is returned)


class ArchiveQARequest(BaseModel):
    question: str
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)


class MailArchiveRequest(BaseModel):
    confirmed_ids: list[str]
    thread_id: str = ""  # triage session; the graph interrupt lives on this thread


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
    cached_emails: list[Email] = overrides.get("emails", [])

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
        return build_graph(store, embedder, llm, wiki, mail_service).compile(
            checkpointer=checkpointer
        )

    compiled_graph = build_compiled()

    def activate_settings(settings: Settings) -> None:
        nonlocal llm, embedder, compiled_graph
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
            if settings.active_chat_model:
                llm_model = settings.active_chat_model
            elif active_provider.models:
                chat_models = [m for m in active_provider.models if m.enabled and m.model_type == "chat"]
                if chat_models:
                    llm_model = chat_models[0].id
                else:
                    llm_model = active_provider.models[0].id

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

    register_config_routes(app, activate_settings=activate_settings)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.post("/api/ask")
    def api_ask(req: AskRequest):
        # conversation_id is the LangGraph thread: the checkpointer replays the
        # prior turns (feat-034) and survives restarts via SqliteSaver.
        conversation_id = req.conversation_id or uuid.uuid4().hex
        config = {"configurable": {"thread_id": conversation_id}}
        try:
            result = compiled_graph.invoke(
                {"text": req.question, "intent": "问答"}, config
            )
        except HTTPException:
            raise
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
        pending = [mid for t in triages if (mid := request_archive(t))]
        return {
            "thread_id": thread_id,
            "pending": pending,
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
                    "can_archive": request_archive(t) is not None,
                }
                for t in triages
            ],
        }

    @app.post("/api/mail/archive")
    def api_mail_archive(req: MailArchiveRequest):
        """Archives selected emails after strict human confirmation (graph interrupt).

        Red Line Enforced: the confirm_archive node whitelists confirmed ids against
        the pending set and re-checks the protected flag; protected mail can never
        reach the archive node under any circumstances.
        """
        if not req.thread_id:
            raise HTTPException(status_code=400, detail="thread_id is required")
        config = {"configurable": {"thread_id": req.thread_id}}
        snapshot = compiled_graph.get_state(config)
        if not any(t.interrupts for t in snapshot.tasks):
            return {
                "archived": [],
                "blocked": list(req.confirmed_ids),
                "message": "No pending confirmation on this triage session.",
            }
        try:
            result = compiled_graph.invoke(
                Command(resume={"approved": req.confirmed_ids}), config
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"归档失败: {str(e)[:180]}")
        archived = list(result.get("archived", []))
        blocked = [mid for mid in req.confirmed_ids if mid not in archived]
        return {
            "archived": archived,
            "blocked": blocked,
            "message": f"Archived {len(archived)} message(s). Blocked {len(blocked)} protected item(s).",
        }

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

    @app.delete("/api/documents/{doc_id}")
    def api_delete_document(doc_id: str):
        """Red line: deletion removes the doc's raw file AND all of its vectors."""
        raw_target = None
        for f in wiki.raw_dir.iterdir():
            if f.is_file() and doc_id_for_origin(str(f.resolve())) == doc_id:
                raw_target = f
                break
        if raw_target is None and doc_id not in store.documents():
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

        store.delete_document(doc_id)
        if doc_id in store.documents():  # paranoia guard on the red line
            raise HTTPException(status_code=500, detail="Orphan vectors remain after deletion")
        raw_name = raw_target.name if raw_target else None
        if raw_target is not None:
            raw_target.unlink()  # source came from raw_dir iteration, so path-safe
        wiki.append_log(f"删除文档 {doc_id}：全部向量与 raw 文件（{raw_name or '无'}）已清除")
        return {"deleted": doc_id, "raw_removed": raw_name}

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

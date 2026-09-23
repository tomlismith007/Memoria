"""FastAPI application providing Web APIs for Memoria.

Serves RAG hybrid search, Wiki explorer, Mail triage, and dual-ingest pipelines.
Supports dependency injection for 100% offline, deterministic testing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from memoria.llm import ChatLLM, OpenAICompatibleChat
from memoria.mail import Email, archive, classify, fetch_messages, is_protected, request_archive
from memoria.rag import ChromaStore, Citation, OpenAICompatibleEmbedder
from memoria.sync import archive_qa, dual_ingest, hybrid_answer
from memoria.web.config import Settings, load_settings, save_settings
from memoria.wiki import Wiki, extract_links, lint as wiki_lint


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)


class ArchiveQARequest(BaseModel):
    question: str
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)


class MailArchiveRequest(BaseModel):
    confirmed_ids: list[str]


class IngestTextRequest(BaseModel):
    text: str
    origin: str = "web_input.md"


def create_app(overrides: dict[str, Any] | None = None) -> FastAPI:
    app = FastAPI(title="Memoria Web API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
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

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/config")
    def api_get_config():
        s = load_settings()
        masked_llm_key = (
            f"{s.llm_api_key[:4]}...{s.llm_api_key[-4:]}"
            if len(s.llm_api_key) > 8
            else ("***" if s.llm_api_key else "")
        )
        return {
            "llm_base_url": s.llm_base_url,
            "llm_api_key": s.llm_api_key,
            "llm_model": s.llm_model,
            "embed_base_url": s.embed_base_url,
            "embed_api_key": s.embed_api_key,
            "embed_model": s.embed_model,
            "demo_mode": s.demo_mode,
            "masked_llm_key": masked_llm_key,
        }

    @app.post("/api/config")
    def api_save_config(req: Settings):
        save_settings(req)
        nonlocal llm, embedder
        if req.demo_mode:
            from memoria.llm import FakeChat
            from memoria.rag import FakeEmbedder

            llm = FakeChat()
            embedder = FakeEmbedder()
        else:
            if "llm" not in overrides:
                llm = OpenAICompatibleChat(
                    base_url=req.llm_base_url,
                    api_key=req.llm_api_key or "no-key",
                    model=req.llm_model,
                )
            if "embedder" not in overrides:
                embedder = OpenAICompatibleEmbedder(
                    base_url=req.embed_base_url,
                    api_key=req.embed_api_key or "no-key",
                    model=req.embed_model,
                )
        return {"status": "ok", "message": "Settings saved successfully"}

    @app.post("/api/ask")
    def api_ask(req: AskRequest):
        ans = hybrid_answer(req.question, wiki, llm, store, embedder)
        return {
            "text": ans.text,
            "source": ans.source,
            "wiki_pages": ans.wiki_pages,
            "citations": [
                {
                    "ref": c.ref,
                    "doc_id": c.doc_id,
                    "chunk": c.chunk,
                    "start": c.start,
                }
                for c in ans.citations
            ],
        }

    @app.get("/api/wiki/pages")
    def api_wiki_pages():
        pages = wiki.list_pages()
        report = wiki_lint(wiki)
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
        emails = list(cached_emails)
        if mail_service is not None:
            try:
                emails = fetch_messages(mail_service)
            except Exception as e:
                return {"triages": [], "error": str(e)}

        results = []
        for e in emails:
            t = classify(e, llm)
            can_archive = request_archive(t) is not None
            results.append({
                "id": t.email.msg_id,
                "msg_id": t.email.msg_id,
                "subject": t.email.subject,
                "sender": t.email.sender,
                "snippet": t.email.snippet,
                "category": t.category,
                "summary": t.summary,
                "protected": t.protected,
                "can_archive": can_archive,
            })
        return {"triages": results}

    @app.post("/api/mail/archive")
    def api_mail_archive(req: MailArchiveRequest):
        """Archives selected emails after strict human confirmation.
        
        Red Line Enforced: Protected emails cannot be archived under any circumstances.
        """
        archived: list[str] = []
        blocked: list[str] = []

        # Find emails to inspect protection status
        email_map = {e.msg_id: e for e in cached_emails}

        for mid in req.confirmed_ids:
            e = email_map.get(mid)
            if e and is_protected(e.subject, e.snippet):
                blocked.append(mid)
                continue
            if mail_service is not None:
                try:
                    archive(mail_service, mid, confirmed=True)
                    archived.append(mid)
                except Exception:
                    blocked.append(mid)
            else:
                # Mock / offline success when confirmed=True
                archived.append(mid)

        return {
            "archived": archived,
            "blocked": blocked,
            "message": f"Archived {len(archived)} message(s). Blocked {len(blocked)} protected item(s).",
        }

    @app.post("/api/ingest")
    def api_ingest(req: IngestTextRequest):
        # Write to raw/ if needed or pass directly to dual_ingest
        # Note: raw/ is read-only for agent/LLM compilation, but user inputs are source
        temp_source = wiki.raw_dir / req.origin
        temp_source.write_text(req.text, encoding="utf-8")
        res = dual_ingest(str(temp_source), store, embedder, wiki, llm)
        return {
            "doc_id": res.doc_id,
            "chunks": res.chunks,
            "wiki_pages": res.wiki_pages,
            "origin": req.origin,
        }

    @app.post("/api/ingest/file")
    async def api_ingest_file(file: UploadFile = File(...)):
        content = await file.read()
        target_path = wiki.raw_dir / file.filename
        target_path.write_bytes(content)
        res = dual_ingest(str(target_path), store, embedder, wiki, llm)
        return {
            "doc_id": res.doc_id,
            "chunks": res.chunks,
            "wiki_pages": res.wiki_pages,
            "filename": file.filename,
        }

    # Mount frontend static files if built
    frontend_dist = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()

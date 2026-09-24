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
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from memoria.llm import ChatLLM, OpenAICompatibleChat
from memoria.mail import Email, archive, classify, fetch_messages, is_protected, request_archive
from memoria.rag import ChromaStore, Citation, OpenAICompatibleEmbedder
from memoria.sync import archive_qa, dual_ingest, hybrid_answer
from memoria.web.config import (
    ModelPreset,
    ModelsRequest,
    Settings,
    TestConfigRequest,
    fetch_remote_models,
    load_settings,
    save_settings,
    test_model_connectivity,
)
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


class PresetSaveRequest(Settings):
    name: str


def _masked_secret(value: str) -> str:
    if len(value) > 8:
        return f"{value[:4]}...{value[-4:]}"
    return "***" if value else ""


def _public_preset(preset: ModelPreset) -> dict[str, Any]:
    return {
        "name": preset.name,
        "llm_base_url": preset.llm_base_url,
        "llm_model": preset.llm_model,
        "llm_api_key_set": bool(preset.llm_api_key),
        "masked_llm_key": _masked_secret(preset.llm_api_key),
        "embed_base_url": preset.embed_base_url,
        "embed_model": preset.embed_model,
        "embed_api_key_set": bool(preset.embed_api_key),
        "masked_embed_key": _masked_secret(preset.embed_api_key),
        "demo_mode": preset.demo_mode,
    }


def _public_settings(settings: Settings) -> dict[str, Any]:
    return {
        "llm_base_url": settings.llm_base_url,
        "llm_model": settings.llm_model,
        "llm_api_key_set": bool(settings.llm_api_key),
        "masked_llm_key": _masked_secret(settings.llm_api_key),
        "embed_base_url": settings.embed_base_url,
        "embed_model": settings.embed_model,
        "embed_api_key_set": bool(settings.embed_api_key),
        "masked_embed_key": _masked_secret(settings.embed_api_key),
        "demo_mode": settings.demo_mode,
        "presets": [_public_preset(preset) for preset in settings.presets],
    }


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
    latest_candidates: set[str] = set()

    def activate_settings(settings: Settings) -> None:
        nonlocal llm, embedder
        if settings.demo_mode:
            from memoria.llm import FakeChat
            from memoria.rag import FakeEmbedder

            llm = FakeChat()
            embedder = FakeEmbedder()
            return
        if "llm" not in overrides:
            llm = OpenAICompatibleChat(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key or "no-key",
                model=settings.llm_model,
            )
        if "embedder" not in overrides:
            embedder = OpenAICompatibleEmbedder(
                base_url=settings.embed_base_url,
                api_key=settings.embed_api_key or "no-key",
                model=settings.embed_model,
            )

    def persist_and_activate(settings: Settings) -> None:
        save_settings(settings)
        activate_settings(settings)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/config")
    def api_get_config():
        return _public_settings(load_settings())

    @app.post("/api/config")
    def api_save_config(req: Settings):
        current = load_settings()
        effective = req.model_copy(update={
            "llm_api_key": req.llm_api_key.strip() or current.llm_api_key,
            "embed_api_key": req.embed_api_key.strip() or current.embed_api_key,
            "presets": current.presets,
        })
        persist_and_activate(effective)
        return {"status": "ok", "message": "Settings saved successfully"}

    @app.post("/api/config/presets")
    def api_save_preset(req: PresetSaveRequest):
        name = req.name.strip()
        if (
            not name
            or len(name) > 64
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
            or any(ord(char) < 32 for char in name)
        ):
            raise HTTPException(status_code=400, detail="Preset name must be 1-64 safe characters")
        current = load_settings()
        if len(current.presets) >= 10:
            raise HTTPException(status_code=409, detail="Preset limit reached")
        if any(preset.name.casefold() == name.casefold() for preset in current.presets):
            raise HTTPException(status_code=409, detail="Preset name already exists")
        preset = ModelPreset(
            name=name,
            llm_base_url=req.llm_base_url,
            llm_api_key=req.llm_api_key.strip() or current.llm_api_key,
            llm_model=req.llm_model,
            embed_base_url=req.embed_base_url,
            embed_api_key=req.embed_api_key.strip() or current.embed_api_key,
            embed_model=req.embed_model,
            demo_mode=req.demo_mode,
        )
        updated = current.model_copy(update={"presets": [*current.presets, preset]})
        save_settings(updated)
        return {"status": "ok", "preset": _public_preset(preset)}

    @app.post("/api/config/presets/{name}/apply")
    def api_apply_preset(name: str):
        current = load_settings()
        preset = next((p for p in current.presets if p.name.casefold() == name.casefold()), None)
        if preset is None:
            raise HTTPException(status_code=404, detail="Preset not found")
        effective = current.model_copy(update=preset.model_dump(exclude={"name"}))
        persist_and_activate(effective)
        return {"status": "ok", "config": _public_settings(effective)}

    @app.delete("/api/config/presets/{name}")
    def api_delete_preset(name: str):
        current = load_settings()
        remaining = [p for p in current.presets if p.name.casefold() != name.casefold()]
        if len(remaining) == len(current.presets):
            raise HTTPException(status_code=404, detail="Preset not found")
        updated = current.model_copy(update={"presets": remaining})
        save_settings(updated)
        return {
            "status": "ok",
            "presets": [_public_preset(preset) for preset in remaining],
        }

    @app.post("/api/config/models")
    def api_fetch_models(req: ModelsRequest):
        try:
            models = fetch_remote_models(req.base_url, req.api_key)
            return {"status": "ok", "models": models}
        except Exception as e:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": f"获取模型失败: {str(e)[:150]}", "models": []},
            )

    @app.post("/api/config/test")
    def api_test_config(req: TestConfigRequest):
        res = test_model_connectivity(req)
        return {"status": "ok", **res}

    @app.post("/api/ask")
    def api_ask(req: AskRequest):
        try:
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
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"LLM 接口调用失败: {str(e)[:180]}")

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
        latest_candidates.clear()
        emails = list(cached_emails)
        if mail_service is not None:
            try:
                emails = fetch_messages(mail_service)
            except Exception as e:
                return {"triages": [], "error": str(e)}

        results = []
        candidate_ids: set[str] = set()
        for e in emails:
            t = classify(e, llm)
            can_archive = request_archive(t) is not None
            if can_archive:
                candidate_ids.add(t.email.msg_id)
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
        latest_candidates.update(candidate_ids)
        return {"triages": results}

    @app.post("/api/mail/archive")
    def api_mail_archive(req: MailArchiveRequest):
        """Archives selected emails after strict human confirmation.

        Red Line Enforced: Protected emails cannot be archived under any circumstances.
        """
        archived: list[str] = []
        blocked: list[str] = []
        email_map = {e.msg_id: e for e in cached_emails}

        for mid in req.confirmed_ids:
            if mid not in latest_candidates:
                blocked.append(mid)
                continue
            e = email_map.get(mid)
            if e and is_protected(e.subject, e.snippet):
                blocked.append(mid)
                continue
            if mail_service is not None:
                try:
                    archive(mail_service, mid, confirmed=True)
                except Exception:
                    blocked.append(mid)
                    continue
            archived.append(mid)
            latest_candidates.discard(mid)

        return {
            "archived": archived,
            "blocked": blocked,
            "message": f"Archived {len(archived)} message(s). Blocked {len(blocked)} protected item(s).",
        }

    @app.post("/api/ingest")
    def api_ingest(req: IngestTextRequest):
        # User inputs are written once; LLM/agent compilation treats raw/ as read-only.
        temp_source = _safe_raw_path(wiki.raw_dir, req.origin)
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
        target_path = _safe_raw_path(wiki.raw_dir, file.filename or "")
        content = await file.read()
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

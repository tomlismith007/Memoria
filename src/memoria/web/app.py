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

from memoria.llm import ChatLLM, OpenAICompatibleChat, normalize_api_format
from memoria.mail import Email, archive, classify, fetch_messages, is_protected, request_archive
from memoria.net import SafeRequestError, validate_public_https_url
from memoria.rag import ChromaStore, Citation, OpenAICompatibleEmbedder
from memoria.sync import archive_qa, dual_ingest, hybrid_answer
from memoria.web.config import (
    CustomModel,
    CustomProvider,
    DEFAULT_LLM_MODEL,
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


class ProviderSaveRequest(BaseModel):
    id: str = ""
    name: str
    base_url: str
    api_format: str = "chat_completions"
    api_key: str = ""
    enabled: bool = True
    active_chat_model: str = ""
    active_embed_model: str = ""


class ModelItemRequest(BaseModel):
    id: str
    name: str = ""
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    model_type: str = "chat"


class ProviderTestRequest(BaseModel):
    model_id: str = ""


class ActivateModelRequest(BaseModel):
    provider_id: str
    model_id: str = ""
    model_type: str = "chat"


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


def _public_model(model: CustomModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "name": model.name or model.id,
        "tags": model.tags,
        "enabled": model.enabled,
        "model_type": model.model_type,
    }


def _public_provider(provider: CustomProvider) -> dict[str, Any]:
    return {
        "id": provider.id,
        "name": provider.name,
        "base_url": provider.base_url,
        "api_format": provider.api_format,
        "api_key_set": bool(provider.api_key),
        "masked_api_key": _masked_secret(provider.api_key),
        "enabled": provider.enabled,
        "models": [_public_model(m) for m in provider.models],
    }


def _public_settings(settings: Settings) -> dict[str, Any]:
    return {
        "active_provider_id": settings.active_provider_id,
        "active_chat_model": settings.active_chat_model,
        "active_embed_model": settings.active_embed_model,
        "providers": [_public_provider(p) for p in settings.providers],
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


def _validate_config_urls(llm_base_url: str, embed_base_url: str = "") -> None:
    try:
        validate_public_https_url(llm_base_url)
        if embed_base_url:
            validate_public_https_url(embed_base_url)
    except SafeRequestError as exc:
        raise HTTPException(status_code=400, detail="公网 HTTPS/443 网关地址无效") from exc


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

        if settings.active_embed_model and active_provider and active_provider.enabled:
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
        _validate_config_urls(req.llm_base_url, req.embed_base_url)
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
        _validate_config_urls(req.llm_base_url, req.embed_base_url)
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
        _validate_config_urls(effective.llm_base_url, effective.embed_base_url)
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
        _validate_config_urls(req.base_url)
        try:
            models = fetch_remote_models(req.base_url, req.api_key, req.api_format)
            return {"status": "ok", "models": models}
        except Exception:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "获取模型失败", "models": []},
            )

    @app.post("/api/config/test")
    def api_test_config(req: TestConfigRequest):
        _validate_config_urls(req.llm_base_url, req.embed_base_url)
        res = test_model_connectivity(req)
        return {"status": "ok", **res}

    @app.get("/api/config/providers")
    def api_get_providers():
        current = load_settings()
        return {
            "status": "ok",
            "active_provider_id": current.active_provider_id,
            "active_chat_model": current.active_chat_model,
            "active_embed_model": current.active_embed_model,
            "providers": [_public_provider(p) for p in current.providers],
        }

    @app.post("/api/config/providers")
    def api_save_provider(req: ProviderSaveRequest):
        _validate_config_urls(req.base_url)
        name = req.name.strip()
        if not name or len(name) > 64:
            raise HTTPException(status_code=400, detail="供应商名称长度必须在 1-64 个字符之间")

        current = load_settings()
        providers = list(current.providers)
        try:
            api_format = normalize_api_format(req.api_format)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="不支持的模型 API 协议") from exc

        provider_id = req.id.strip()
        if not provider_id:
            import re
            base_slug = re.sub(r"[^a-zA-Z0-9_\-]+", "-", name.lower()).strip("-") or "provider"
            provider_id = base_slug
            idx = 1
            while any(p.id == provider_id for p in providers):
                provider_id = f"{base_slug}-{idx}"
                idx += 1

        existing = next((p for p in providers if p.id == provider_id), None)
        if existing:
            api_key = req.api_key.strip() if req.api_key.strip() else existing.api_key
            saved_provider = existing.model_copy(update={
                "name": name,
                "base_url": req.base_url,
                "api_format": api_format,
                "api_key": api_key,
                "enabled": req.enabled,
            })
            providers = [saved_provider if p.id == provider_id else p for p in providers]
        else:
            saved_provider = CustomProvider(
                id=provider_id,
                name=name,
                base_url=req.base_url,
                api_format=api_format,
                api_key=req.api_key.strip(),
                enabled=req.enabled,
                models=[],
            )
            providers.append(saved_provider)

        active_id = current.active_provider_id
        if (not active_id or active_id == saved_provider.id) and saved_provider.enabled:
            active_id = saved_provider.id

        active_chat = current.active_chat_model
        if req.active_chat_model:
            active_chat = req.active_chat_model
        elif not active_chat and saved_provider.models:
            active_chat = saved_provider.models[0].id

        active_embed = current.active_embed_model
        if req.active_embed_model:
            active_embed = req.active_embed_model

        updated_settings = current.model_copy(update={
            "providers": providers,
            "active_provider_id": active_id,
            "active_chat_model": active_chat,
            "active_embed_model": active_embed,
            "llm_base_url": saved_provider.base_url,
            "llm_api_key": saved_provider.api_key or current.llm_api_key,
            "llm_model": active_chat or current.llm_model,
        })
        persist_and_activate(updated_settings)
        return {"status": "ok", "provider": _public_provider(saved_provider)}

    @app.delete("/api/config/providers/{provider_id}")
    def api_delete_provider(provider_id: str):
        current = load_settings()
        remaining = [p for p in current.providers if p.id != provider_id]
        if len(remaining) == len(current.providers):
            raise HTTPException(status_code=404, detail="Provider not found")
        active_id = current.active_provider_id
        active_model = current.active_chat_model
        if active_id == provider_id:
            enabled_remaining = [p for p in remaining if p.enabled]
            if enabled_remaining:
                active_id = enabled_remaining[0].id
                active_model = enabled_remaining[0].models[0].id if enabled_remaining[0].models else ""
            else:
                active_id = ""
                active_model = ""

        updated = current.model_copy(update={
            "providers": remaining,
            "active_provider_id": active_id,
            "active_chat_model": active_model,
        })
        persist_and_activate(updated)
        return {"status": "ok", "providers": [_public_provider(p) for p in remaining]}

    @app.post("/api/config/providers/{provider_id}/models")
    def api_save_provider_model(provider_id: str, req: ModelItemRequest):
        current = load_settings()
        provider = next((p for p in current.providers if p.id == provider_id), None)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

        model_id = req.id.strip()
        if not model_id:
            raise HTTPException(status_code=400, detail="模型 ID 不能为空")

        models = list(provider.models)
        existing = next((m for m in models if m.id == model_id), None)
        if existing:
            saved_model = existing.model_copy(update={
                "name": req.name.strip() or model_id,
                "tags": req.tags,
                "enabled": req.enabled,
                "model_type": req.model_type,
            })
            models = [saved_model if m.id == model_id else m for m in models]
        else:
            saved_model = CustomModel(
                id=model_id,
                name=req.name.strip() or model_id,
                tags=req.tags,
                enabled=req.enabled,
                model_type=req.model_type,
            )
            models.append(saved_model)

        updated_provider = provider.model_copy(update={"models": models})
        providers = [updated_provider if p.id == provider_id else p for p in current.providers]

        active_chat = current.active_chat_model
        if provider_id == current.active_provider_id and not active_chat and saved_model.enabled and saved_model.model_type == "chat":
            active_chat = saved_model.id

        updated_settings = current.model_copy(update={
            "providers": providers,
            "active_chat_model": active_chat,
        })
        persist_and_activate(updated_settings)
        return {
            "status": "ok",
            "model": _public_model(saved_model),
            "provider": _public_provider(updated_provider),
        }

    @app.delete("/api/config/providers/{provider_id}/models/{model_id:path}")
    def api_delete_provider_model(provider_id: str, model_id: str):
        current = load_settings()
        provider = next((p for p in current.providers if p.id == provider_id), None)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

        remaining = [m for m in provider.models if m.id != model_id]
        if len(remaining) == len(provider.models):
            raise HTTPException(status_code=404, detail="Model not found")

        updated_provider = provider.model_copy(update={"models": remaining})
        providers = [updated_provider if p.id == provider_id else p for p in current.providers]

        active_chat = current.active_chat_model
        if provider_id == current.active_provider_id and active_chat == model_id:
            chat_models = [m for m in remaining if m.enabled and m.model_type == "chat"]
            active_chat = chat_models[0].id if chat_models else ""

        updated_settings = current.model_copy(update={
            "providers": providers,
            "active_chat_model": active_chat,
        })
        persist_and_activate(updated_settings)
        return {"status": "ok", "provider": _public_provider(updated_provider)}

    @app.post("/api/config/providers/{provider_id}/test")
    def api_test_provider(provider_id: str, req: ProviderTestRequest | None = None):
        current = load_settings()
        provider = next((p for p in current.providers if p.id == provider_id), None)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

        _validate_config_urls(provider.base_url)
        model_id = req.model_id.strip() if req and req.model_id else ""
        if not model_id and provider.models:
            model_id = provider.models[0].id

        test_req = TestConfigRequest(
            llm_base_url=provider.base_url,
            llm_api_key=provider.api_key,
            llm_model=model_id or DEFAULT_LLM_MODEL,
            api_format=provider.api_format,
            embed_base_url="",
            embed_api_key="",
            embed_model="",
        )
        res = test_model_connectivity(test_req)
        return {"status": "ok", **res}

    @app.post("/api/config/providers/activate")
    def api_activate_provider(req: ActivateModelRequest):
        current = load_settings()
        provider = next((p for p in current.providers if p.id == req.provider_id), None)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

        active_chat = current.active_chat_model
        active_embed = current.active_embed_model

        if req.model_id:
            if req.model_type == "embedding":
                active_embed = req.model_id
            else:
                active_chat = req.model_id
        elif provider.models:
            chat_models = [m for m in provider.models if m.enabled and m.model_type == "chat"]
            if chat_models:
                active_chat = chat_models[0].id
            else:
                active_chat = provider.models[0].id

        updated = current.model_copy(update={
            "active_provider_id": provider.id,
            "active_chat_model": active_chat,
            "active_embed_model": active_embed,
            "llm_base_url": provider.base_url,
            "llm_api_key": provider.api_key or current.llm_api_key,
            "llm_model": active_chat or current.llm_model,
        })
        persist_and_activate(updated)
        return {
            "status": "ok",
            "active_provider_id": updated.active_provider_id,
            "active_chat_model": updated.active_chat_model,
            "active_embed_model": updated.active_embed_model,
        }

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

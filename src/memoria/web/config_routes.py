"""Configuration routes for the Memoria Web API."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from memoria.llm import normalize_api_format
from memoria.net import SafeRequestError, validate_public_https_url
from memoria.web.config import (
    CustomModel,
    CustomProvider,
    DEFAULT_LLM_MODEL,
    ModelsRequest,
    Settings,
    TestConfigRequest,
    fetch_remote_models,
    load_settings,
    pick_model_id,
    resolve_active_chat_model,
    save_settings,
    test_model_connectivity,
)


class ProviderSaveRequest(BaseModel):
    id: str = ""
    name: str
    base_url: str
    api_format: str = "chat_completions"
    api_key: str = ""
    enabled: bool = True
    scope: str = "chat"
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
    model_type: str = "chat"


class ActivateModelRequest(BaseModel):
    provider_id: str
    model_id: str = ""
    model_type: str = "chat"


def _masked_secret(value: str) -> str:
    if len(value) > 8:
        return f"{value[:4]}...{value[-4:]}"
    return "***" if value else ""


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


def _validate_config_urls(llm_base_url: str = "", embed_base_url: str = "") -> None:
    if not llm_base_url and not embed_base_url:
        raise HTTPException(status_code=400, detail="公网 HTTPS/443 网关地址无效")
    try:
        if llm_base_url:
            validate_public_https_url(llm_base_url)
        if embed_base_url:
            validate_public_https_url(embed_base_url)
    except SafeRequestError as exc:
        raise HTTPException(status_code=400, detail="公网 HTTPS/443 网关地址无效") from exc


def register_config_routes(
    app: FastAPI,
    *,
    activate_settings: Callable[[Settings], None],
) -> None:
    """Register configuration routes while preserving runtime activation."""

    def persist_and_activate(settings: Settings) -> None:
        save_settings(settings)
        activate_settings(settings)

    @app.post("/api/config/models")
    def api_fetch_models(req: ModelsRequest):
        _validate_config_urls(req.base_url)
        api_key = req.api_key.strip()
        if not api_key and req.provider_id:
            # feat-056: the settings UI only ever holds a masked key, so fetching
            # models for a saved provider sent an empty Authorization header and
            # every gateway answered 401. Fall back to the stored credential.
            stored = next(
                (p for p in load_settings().providers if p.id == req.provider_id), None
            )
            api_key = (stored.api_key or "") if stored else ""
        try:
            models = fetch_remote_models(req.base_url, api_key, req.api_format)
            return {"status": "ok", "models": models}
        except Exception as exc:
            # Surface the real reason: a bare "获取模型失败" left the user unable
            # to tell a bad key from an unreachable host.
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": f"获取模型失败：{str(exc)[:180]}",
                    "models": [],
                },
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
            "active_embed_provider_id": current.active_embed_provider_id,
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

        updates: dict[str, Any] = {"providers": providers}

        if req.scope != "embedding":
            active_id = current.active_provider_id
            if (not active_id or active_id == saved_provider.id) and saved_provider.enabled:
                active_id = saved_provider.id

            active_chat = current.active_chat_model
            if active_id == saved_provider.id:
                if req.active_chat_model:
                    match = next(
                        (m for m in saved_provider.models if m.id == req.active_chat_model), None
                    )
                    if match and match.model_type != "chat":
                        active_chat = pick_model_id(saved_provider, "chat")
                    else:
                        active_chat = req.active_chat_model
                elif not active_chat:
                    active_chat = pick_model_id(saved_provider, "chat")

            updates.update({
                "active_provider_id": active_id,
                "active_chat_model": active_chat,
            })
            if saved_provider.enabled and active_id == saved_provider.id:
                updates.update({
                    "llm_base_url": saved_provider.base_url,
                    "llm_api_key": saved_provider.api_key or current.llm_api_key,
                    "llm_model": active_chat or current.llm_model,
                })

        updated_settings = current.model_copy(update=updates)
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
                active_model = pick_model_id(enabled_remaining[0], "chat")
            else:
                active_id = ""
                active_model = ""

        updates = {
            "providers": remaining,
            "active_provider_id": active_id,
            "active_chat_model": active_model,
        }
        if current.active_embed_provider_id == provider_id:
            updates.update({
                "active_embed_provider_id": "",
                "active_embed_model": "",
            })
        updated = current.model_copy(update=updates)
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
        updates = {
            "providers": providers,
            "active_chat_model": active_chat,
        }
        # Re-saving an id with a new type converts it (the gateway never serves
        # one id as two types, so a mismatch means the stored type was wrong).
        # A converted-away model can no longer be the active embedding — clear
        # the selector instead of pointing it at a chat model.
        if (
            existing
            and existing.model_type != saved_model.model_type
            and current.active_embed_provider_id == provider_id
            and current.active_embed_model == model_id
        ):
            updates["active_embed_provider_id"] = ""
            updates["active_embed_model"] = ""
        if (
            saved_model.model_type == "embedding"
            and saved_model.enabled
            and not current.active_embed_model
        ):
            updates.update({
                "active_embed_provider_id": provider_id,
                "active_embed_model": saved_model.id,
            })
        updated_settings = current.model_copy(update=updates)
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

        updates = {
            "providers": providers,
            "active_chat_model": active_chat,
        }
        if provider_id == current.active_embed_provider_id:
            active_embed_model = current.active_embed_model
            if active_embed_model == model_id:
                embedding_models = [
                    m for m in remaining if m.enabled and m.model_type == "embedding"
                ]
                if embedding_models:
                    updates.update({
                        "active_embed_model": embedding_models[0].id,
                    })
                else:
                    updates.update({
                        "active_embed_provider_id": "",
                        "active_embed_model": "",
                    })
        updated_settings = current.model_copy(update=updates)
        persist_and_activate(updated_settings)
        return {"status": "ok", "provider": _public_provider(updated_provider)}

    @app.post("/api/config/providers/{provider_id}/test")
    def api_test_provider(provider_id: str, req: ProviderTestRequest | None = None):
        current = load_settings()
        provider = next((p for p in current.providers if p.id == provider_id), None)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

        _validate_config_urls(provider.base_url)
        model_type = req.model_type if req and req.model_type == "embedding" else "chat"
        model_id = req.model_id.strip() if req and req.model_id else ""
        if not model_id and provider.models:
            matching_models = [
                m for m in provider.models
                if m.enabled and m.model_type == model_type
            ]
            model_id = matching_models[0].id if matching_models else provider.models[0].id

        if model_type == "embedding":
            test_req = TestConfigRequest(
                llm_base_url="",
                llm_api_key="",
                llm_model="",
                api_format="chat_completions",
                embed_base_url=provider.base_url,
                embed_api_key=provider.api_key,
                embed_model=model_id,
            )
        else:
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
        if not provider.enabled:
            raise HTTPException(status_code=400, detail="不能激活已禁用的供应商")

        # Write-boundary guard on config integrity: an explicit activation must
        # match the model's stored type. Pill clicks used to activate embedding
        # models as chat, which corrupted the live config (user report).
        if req.model_id:
            existing_model = next(
                (m for m in provider.models if m.id == req.model_id), None
            )
            if existing_model is not None and existing_model.model_type != req.model_type:
                kind = "向量" if existing_model.model_type == "embedding" else "对话"
                target = "向量" if req.model_type == "embedding" else "对话"
                raise HTTPException(
                    status_code=400,
                    detail=f"{req.model_id} 是{kind}模型，不能设为{target}模型",
                )

        if req.model_type == "embedding":
            active_embed = req.model_id or pick_model_id(provider, "embedding")
            updated = current.model_copy(update={
                "active_embed_provider_id": provider.id,
                "active_embed_model": active_embed,
            })
        else:
            active_chat = req.model_id or pick_model_id(provider, "chat")
            updated = current.model_copy(update={
                "active_provider_id": provider.id,
                "active_chat_model": active_chat,
                "llm_base_url": provider.base_url,
                "llm_api_key": provider.api_key or current.llm_api_key,
                "llm_model": active_chat or current.llm_model,
            })
        persist_and_activate(updated)
        return {
            "status": "ok",
            "active_provider_id": updated.active_provider_id,
            "active_chat_model": updated.active_chat_model,
            "active_embed_provider_id": updated.active_embed_provider_id,
            "active_embed_model": updated.active_embed_model,
        }

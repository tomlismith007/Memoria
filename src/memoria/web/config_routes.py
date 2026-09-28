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
    ModelPreset,
    ModelsRequest,
    Settings,
    TestConfigRequest,
    fetch_remote_models,
    load_settings,
    save_settings,
    test_model_connectivity,
)


class PresetSaveRequest(Settings):
    name: str


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
        "active_embed_provider_id": settings.active_embed_provider_id,
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


def register_config_routes(
    app: FastAPI,
    *,
    activate_settings: Callable[[Settings], None],
) -> None:
    """Register configuration routes while preserving runtime activation."""

    def persist_and_activate(settings: Settings) -> None:
        save_settings(settings)
        activate_settings(settings)

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
                    active_chat = req.active_chat_model
                elif not active_chat and saved_provider.models:
                    active_chat = saved_provider.models[0].id

            active_embed = current.active_embed_model
            if req.active_embed_model:
                active_embed = req.active_embed_model

            updates.update({
                "active_provider_id": active_id,
                "active_chat_model": active_chat,
                "active_embed_model": active_embed,
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
                active_model = enabled_remaining[0].models[0].id if enabled_remaining[0].models else ""
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

        if req.model_type == "embedding":
            if req.model_id:
                active_embed_model = req.model_id
            else:
                embedding_models = [
                    m for m in provider.models if m.enabled and m.model_type == "embedding"
                ]
                active_embed_model = embedding_models[0].id if embedding_models else ""
            updated = current.model_copy(update={
                "active_embed_provider_id": provider.id,
                "active_embed_model": active_embed_model,
            })
            persist_and_activate(updated)
            return {
                "status": "ok",
                "active_provider_id": updated.active_provider_id,
                "active_chat_model": updated.active_chat_model,
                "active_embed_provider_id": updated.active_embed_provider_id,
                "active_embed_model": updated.active_embed_model,
            }

        active_chat = current.active_chat_model
        if req.model_id:
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

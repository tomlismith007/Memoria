"""Configuration persistence and runtime settings for Memoria Web."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field

from memoria.llm import (
    API_FORMAT_ANTHROPIC_MESSAGES,
    API_FORMAT_CHAT_COMPLETIONS,
    build_chat_request,
    normalize_api_format,
)
from memoria.net import SafeRequestError, safe_request, validate_public_https_url

DEFAULT_SETTINGS_PATH = Path("./data/settings.json")
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_EMBED_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"


class ModelPreset(BaseModel):
    name: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    embed_base_url: str
    embed_api_key: str
    embed_model: str
    demo_mode: bool = False


class CustomModel(BaseModel):
    id: str
    name: str = ""
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    model_type: str = "chat"


ApiFormat = Annotated[str, BeforeValidator(normalize_api_format)]


class CustomProvider(BaseModel):
    id: str
    name: str
    base_url: str
    api_format: ApiFormat = API_FORMAT_CHAT_COMPLETIONS
    api_key: str = ""
    enabled: bool = True
    models: list[CustomModel] = Field(default_factory=list)


class Settings(BaseModel):
    active_provider_id: str = ""
    active_chat_model: str = ""
    active_embed_provider_id: str = ""
    active_embed_model: str = ""
    providers: list[CustomProvider] = Field(default_factory=list)
    llm_base_url: str = Field(default=DEFAULT_LLM_BASE_URL)
    llm_api_key: str = Field(default="")
    llm_model: str = Field(default=DEFAULT_LLM_MODEL)
    embed_base_url: str = Field(default=DEFAULT_EMBED_BASE_URL)
    embed_api_key: str = Field(default="")
    embed_model: str = Field(default=DEFAULT_EMBED_MODEL)
    demo_mode: bool = Field(default=False)
    presets: list[ModelPreset] = Field(default_factory=list)


class ModelsRequest(BaseModel):
    base_url: str
    api_key: str = ""
    api_format: ApiFormat = API_FORMAT_CHAT_COMPLETIONS


class TestConfigRequest(BaseModel):
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_api_key: str = ""
    llm_model: str = DEFAULT_LLM_MODEL
    api_format: ApiFormat = API_FORMAT_CHAT_COMPLETIONS
    embed_base_url: str = ""
    embed_api_key: str = ""
    embed_model: str = ""


def _environment_settings() -> Settings:
    return Settings(
        llm_base_url=os.environ.get(
            "MEMORIA_LLM_BASE_URL", os.environ.get("OPENAI_BASE_URL", DEFAULT_LLM_BASE_URL)
        ),
        llm_api_key=os.environ.get("MEMORIA_LLM_API_KEY", os.environ.get("OPENAI_API_KEY", "")),
        llm_model=os.environ.get("MEMORIA_LLM_MODEL", DEFAULT_LLM_MODEL),
        embed_base_url=os.environ.get(
            "MEMORIA_EMBED_BASE_URL", os.environ.get("OPENAI_BASE_URL", DEFAULT_EMBED_BASE_URL)
        ),
        embed_api_key=os.environ.get("MEMORIA_EMBED_API_KEY", os.environ.get("OPENAI_API_KEY", "")),
        embed_model=os.environ.get("MEMORIA_EMBED_MODEL", DEFAULT_EMBED_MODEL),
        demo_mode=os.environ.get("MEMORIA_DEMO_MODE", "false").lower() in ("1", "true", "yes"),
    )


def _is_public_url(url: str, *, allow_empty: bool = False) -> bool:
    if allow_empty and not url.strip():
        return True
    try:
        validate_public_https_url(url)
    except SafeRequestError:
        return False
    return True


def _fallback_url(value: str, fallback: str) -> str:
    return value if _is_public_url(value) else fallback


def _sanitize_settings(settings: Settings, fallback: Settings) -> Settings:
    llm_url = _fallback_url(settings.llm_base_url, fallback.llm_base_url)
    # A non-empty legacy embedding URL must not survive migration. Empty is the
    # supported way to reuse the LLM gateway at request time.
    embed_url = (
        settings.embed_base_url
        if not settings.embed_base_url.strip() or _is_public_url(settings.embed_base_url)
        else fallback.embed_base_url
    )
    presets = [
        preset
        for preset in settings.presets
        if _is_public_url(preset.llm_base_url)
        and (not preset.embed_base_url.strip() or _is_public_url(preset.embed_base_url))
    ]
    providers = [
        provider
        for provider in settings.providers
        if _is_public_url(provider.base_url)
    ]
    return settings.model_copy(
        update={
            "llm_base_url": llm_url,
            "embed_base_url": embed_url,
            "presets": presets,
            "providers": providers,
        }
    )


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> Settings:
    fallback = _sanitize_settings(_environment_settings(), Settings())
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return _sanitize_settings(Settings(**data), fallback)
        except Exception:
            pass
    return fallback


def save_settings(settings: Settings, path: Path = DEFAULT_SETTINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings.model_dump_json(indent=2), encoding="utf-8")


def _model_auth_headers(api_key: str, api_format: str) -> dict[str, str]:
    protocol = normalize_api_format(api_format)
    if protocol == API_FORMAT_ANTHROPIC_MESSAGES:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def fetch_remote_models(
    base_url: str,
    api_key: str = "",
    api_format: str = API_FORMAT_CHAT_COMPLETIONS,
    timeout: float = 10.0,
) -> list[str]:
    validate_public_https_url(base_url)
    protocol = normalize_api_format(api_format)
    url = f"{base_url.rstrip('/')}/models"
    headers = _model_auth_headers(api_key, protocol)
    resp = safe_request(
        url,
        method="GET",
        headers=headers,
        timeout=timeout,
        max_bytes=1024 * 1024,
    )
    resp.raise_for_status()
    data = resp.json()
    models: list[str] = []
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        for item in data["data"]:
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
                models.append(item["id"])
    return sorted(set(models))


def test_model_connectivity(req: TestConfigRequest, timeout: float = 10.0) -> dict[str, Any]:
    if req.llm_base_url:
        validate_public_https_url(req.llm_base_url)
    if req.embed_base_url:
        validate_public_https_url(req.embed_base_url)

    result: dict[str, Any] = {
        "llm_ok": False,
        "llm_latency_ms": 0,
        "llm_message": "",
        "embed_ok": False,
        "embed_latency_ms": 0,
        "embed_message": "",
    }

    # 1. Test LLM using the selected provider protocol. An empty URL means
    # embedding-only diagnostics (the vector provider is independent).
    t0 = time.perf_counter()
    if not req.llm_base_url:
        result["llm_ok"] = True
        result["llm_message"] = "未选择对话网关，跳过"
    else:
        try:
            url, headers, json_body = build_chat_request(
                req.llm_base_url,
                req.llm_api_key,
                req.llm_model or DEFAULT_LLM_MODEL,
                req.api_format,
                system="",
                user="hi",
                max_tokens=5,
            )
            resp = safe_request(
                url,
                method="POST",
                headers=headers,
                json_body=json_body,
                timeout=timeout,
                max_bytes=1024 * 1024,
            )
            latency = int((time.perf_counter() - t0) * 1000)
            if resp.status == 200:
                result["llm_ok"] = True
                result["llm_latency_ms"] = latency
                result["llm_message"] = f"连接成功 ({latency}ms)"
            else:
                result["llm_message"] = f"HTTP {resp.status}: {resp.text[:120]}"
        except Exception as exc:
            latency = int((time.perf_counter() - t0) * 1000)
            result["llm_latency_ms"] = latency
            result["llm_message"] = f"连接失败: {str(exc)[:120]}"

    # 2. Test Embedding
    embed_url = req.embed_base_url or req.llm_base_url
    embed_key = req.embed_api_key or req.llm_api_key
    embed_model = req.embed_model or DEFAULT_EMBED_MODEL

    if embed_url and embed_model:
        t1 = time.perf_counter()
        try:
            url = f"{embed_url.rstrip('/')}/embeddings"
            headers = {}
            if embed_key:
                headers["Authorization"] = f"Bearer {embed_key}"
            resp = safe_request(
                url,
                method="POST",
                headers=headers,
                json_body={"model": embed_model, "input": "test"},
                timeout=timeout,
                max_bytes=1024 * 1024,
            )
            latency = int((time.perf_counter() - t1) * 1000)
            if resp.status == 200:
                result["embed_ok"] = True
                result["embed_latency_ms"] = latency
                result["embed_message"] = f"连接成功 ({latency}ms)"
            else:
                result["embed_latency_ms"] = latency
                result["embed_message"] = f"HTTP {resp.status}: {resp.text[:120]}"
        except Exception as exc:
            latency = int((time.perf_counter() - t1) * 1000)
            result["embed_latency_ms"] = latency
            result["embed_message"] = f"连接失败: {str(exc)[:120]}"
    else:
        result["embed_ok"] = True
        result["embed_message"] = "未配置独立向量模型，跳过"

    return result

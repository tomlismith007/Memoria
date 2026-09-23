"""Configuration persistence and runtime settings for Memoria Web."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel, Field

DEFAULT_SETTINGS_PATH = Path("./data/settings.json")


class Settings(BaseModel):
    llm_base_url: str = Field(default="https://api.openai.com/v1")
    llm_api_key: str = Field(default="")
    llm_model: str = Field(default="gpt-4o-mini")
    embed_base_url: str = Field(default="https://api.openai.com/v1")
    embed_api_key: str = Field(default="")
    embed_model: str = Field(default="text-embedding-3-small")
    demo_mode: bool = Field(default=False)


class ModelsRequest(BaseModel):
    base_url: str
    api_key: str = ""


class TestConfigRequest(BaseModel):
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    embed_base_url: str = ""
    embed_api_key: str = ""
    embed_model: str = ""


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> Settings:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Settings(**data)
        except Exception:
            pass

    # Fall back to environment variables
    return Settings(
        llm_base_url=os.environ.get("MEMORIA_LLM_BASE_URL", os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")),
        llm_api_key=os.environ.get("MEMORIA_LLM_API_KEY", os.environ.get("OPENAI_API_KEY", "")),
        llm_model=os.environ.get("MEMORIA_LLM_MODEL", "gpt-4o-mini"),
        embed_base_url=os.environ.get("MEMORIA_EMBED_BASE_URL", os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")),
        embed_api_key=os.environ.get("MEMORIA_EMBED_API_KEY", os.environ.get("OPENAI_API_KEY", "")),
        embed_model=os.environ.get("MEMORIA_EMBED_MODEL", "text-embedding-3-small"),
        demo_mode=os.environ.get("MEMORIA_DEMO_MODE", "false").lower() in ("1", "true", "yes"),
    )


def save_settings(settings: Settings, path: Path = DEFAULT_SETTINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings.model_dump_json(indent=2), encoding="utf-8")


def fetch_remote_models(base_url: str, api_key: str = "", timeout: float = 10.0) -> list[str]:
    url = f"{base_url.rstrip('/')}/models"
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    models: list[str] = []
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list):
            for m in data["data"]:
                if isinstance(m, dict) and "id" in m:
                    models.append(str(m["id"]))
                elif isinstance(m, str):
                    models.append(m)
        elif "models" in data and isinstance(data["models"], list):
            for m in data["models"]:
                if isinstance(m, dict) and "name" in m:
                    models.append(str(m["name"]))
                elif isinstance(m, dict) and "id" in m:
                    models.append(str(m["id"]))
                elif isinstance(m, str):
                    models.append(m)
    models.sort()
    return models


def test_model_connectivity(req: TestConfigRequest, timeout: float = 10.0) -> dict[str, Any]:
    result: dict[str, Any] = {
        "llm_ok": False,
        "llm_latency_ms": 0,
        "llm_message": "",
        "embed_ok": False,
        "embed_latency_ms": 0,
        "embed_message": "",
    }

    # 1. Test LLM
    t0 = time.perf_counter()
    try:
        url = f"{req.llm_base_url.rstrip('/')}/chat/completions"
        headers: dict[str, str] = {}
        if req.llm_api_key:
            headers["Authorization"] = f"Bearer {req.llm_api_key}"
        resp = requests.post(
            url,
            headers=headers,
            json={
                "model": req.llm_model or "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5,
            },
            timeout=timeout,
        )
        latency = int((time.perf_counter() - t0) * 1000)
        if resp.status_code == 200:
            result["llm_ok"] = True
            result["llm_latency_ms"] = latency
            result["llm_message"] = f"连接成功 ({latency}ms)"
        else:
            result["llm_ok"] = False
            result["llm_latency_ms"] = latency
            result["llm_message"] = f"HTTP {resp.status_code}: {resp.text[:120]}"
    except Exception as e:
        latency = int((time.perf_counter() - t0) * 1000)
        result["llm_ok"] = False
        result["llm_latency_ms"] = latency
        result["llm_message"] = f"连接失败: {str(e)[:120]}"

    # 2. Test Embedding
    embed_url = req.embed_base_url or req.llm_base_url
    embed_key = req.embed_api_key or req.llm_api_key
    embed_model = req.embed_model or "text-embedding-3-small"

    if embed_url and embed_model:
        t1 = time.perf_counter()
        try:
            url = f"{embed_url.rstrip('/')}/embeddings"
            headers = {}
            if embed_key:
                headers["Authorization"] = f"Bearer {embed_key}"
            resp = requests.post(
                url,
                headers=headers,
                json={"model": embed_model, "input": "test"},
                timeout=timeout,
            )
            latency = int((time.perf_counter() - t1) * 1000)
            if resp.status_code == 200:
                result["embed_ok"] = True
                result["embed_latency_ms"] = latency
                result["embed_message"] = f"连接成功 ({latency}ms)"
            else:
                result["embed_ok"] = False
                result["embed_latency_ms"] = latency
                result["embed_message"] = f"HTTP {resp.status_code}: {resp.text[:120]}"
        except Exception as e:
            latency = int((time.perf_counter() - t1) * 1000)
            result["embed_ok"] = False
            result["embed_latency_ms"] = latency
            result["embed_message"] = f"连接失败: {str(e)[:120]}"
    else:
        result["embed_ok"] = True
        result["embed_message"] = "未配置独立向量模型，跳过"

    return result

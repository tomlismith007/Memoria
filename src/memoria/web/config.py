"""Configuration persistence and runtime settings for Memoria Web."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

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

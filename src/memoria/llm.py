"""Shared chat-LLM interface. Email module reuses this. Tests use FakeChat."""

from __future__ import annotations

import os
from typing import Protocol

import requests


class ChatLLM(Protocol):
    def chat(self, system: str, user: str) -> str: ...


class FakeChat:
    """Canned reply for offline tests. Records calls."""

    def __init__(self, reply: str = "") -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply


class OpenAICompatibleChat:
    """Any /chat/completions-compatible endpoint, configured via env."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.base_url = base_url or os.environ.get(
            "MEMORIA_LLM_BASE_URL", "https://api.openai.com/v1"
        )
        self.api_key = api_key or os.environ.get("MEMORIA_LLM_API_KEY", "")
        self.model = model or os.environ.get("MEMORIA_LLM_MODEL", "gpt-4o-mini")

    def chat(self, system: str, user: str) -> str:
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

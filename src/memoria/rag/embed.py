"""Embedders: OpenAI-compatible API for prod, deterministic fake for tests/offline."""

from __future__ import annotations

import hashlib
import os
import re
from typing import Protocol

from memoria.net import safe_request


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    """Hashed bag-of-words. Deterministic, no network. Tests and offline dev only."""

    def __init__(self, dim: int = 32) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in re.findall(r"\w+", text.lower()):
            vec[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm for v in vec] if norm else vec


class OpenAICompatibleEmbedder:
    """Any /embeddings-compatible endpoint, configured via env (vendor-neutral)."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.base_url = base_url or os.environ.get(
            "MEMORIA_EMBED_BASE_URL", "https://api.openai.com/v1"
        )
        self.api_key = api_key or os.environ.get("MEMORIA_EMBED_API_KEY", "")
        self.model = model or os.environ.get("MEMORIA_EMBED_MODEL", "text-embedding-3-small")

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = safe_request(
            f"{self.base_url.rstrip('/')}/embeddings",
            method="POST",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_body={"model": self.model, "input": texts},
            timeout=60,
            max_bytes=4 * 1024 * 1024,
            allow_ollama=True,
        )
        resp.raise_for_status()
        items = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in items]

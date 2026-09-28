"""Shared chat-LLM interface. Email module reuses this. Tests use FakeChat."""

from __future__ import annotations

import os
from typing import Any, Protocol

from memoria.net import safe_request

API_FORMAT_CHAT_COMPLETIONS = "chat_completions"
API_FORMAT_ANTHROPIC_MESSAGES = "anthropic_messages"
API_FORMAT_OPENAI_RESPONSES = "openai_responses"
SUPPORTED_API_FORMATS = {
    API_FORMAT_CHAT_COMPLETIONS,
    API_FORMAT_ANTHROPIC_MESSAGES,
    API_FORMAT_OPENAI_RESPONSES,
}
_API_FORMAT_ALIASES = {
    "openai": API_FORMAT_CHAT_COMPLETIONS,
    "openai_chat": API_FORMAT_CHAT_COMPLETIONS,
    "openai_chat_completions": API_FORMAT_CHAT_COMPLETIONS,
    "anthropic": API_FORMAT_ANTHROPIC_MESSAGES,
    "claude": API_FORMAT_ANTHROPIC_MESSAGES,
    "responses": API_FORMAT_OPENAI_RESPONSES,
    "openai_response": API_FORMAT_OPENAI_RESPONSES,
    "response": API_FORMAT_OPENAI_RESPONSES,
}


def normalize_api_format(value: str | None, default: str = API_FORMAT_CHAT_COMPLETIONS) -> str:
    """Return a canonical protocol name while accepting legacy aliases."""
    candidate = (value or "").strip().lower().replace("-", "_")
    candidate = _API_FORMAT_ALIASES.get(candidate, candidate)
    if not candidate:
        return default
    if candidate not in SUPPORTED_API_FORMATS:
        raise ValueError(f"Unsupported API format: {value}")
    return candidate


def provider_auth_headers(api_key: str, protocol: str) -> dict[str, str]:
    """Auth headers for a protocol: chat requests and GET /models share one source."""
    if protocol == API_FORMAT_ANTHROPIC_MESSAGES:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def build_chat_request(
    base_url: str,
    api_key: str,
    model: str,
    api_format: str = API_FORMAT_CHAT_COMPLETIONS,
    system: str = "",
    user: str = "",
    max_tokens: int | None = None,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build the provider-specific HTTP request for a chat completion."""
    protocol = normalize_api_format(api_format)
    root = base_url.rstrip("/")
    if protocol == API_FORMAT_ANTHROPIC_MESSAGES:
        headers = provider_auth_headers(api_key, protocol)
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or 4096,
            "messages": [{"role": "user", "content": user}],
        }
        if system:
            # feat-041: mark the system prompt cacheable. Every Memoria prompt leads
            # with a fixed system block, so this is the reusable prefix. Only sent on
            # protocols that accept the marker — a compatible endpoint must not be
            # handed an unknown field.
            body["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        return f"{root}/messages", {key: value for key, value in headers.items() if value}, body

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    if protocol == API_FORMAT_OPENAI_RESPONSES:
        body = {
            "model": model,
            "instructions": system,
            "input": user,
        }
        if max_tokens is not None:
            body["max_output_tokens"] = max_tokens
        return f"{root}/responses", headers, body

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    return f"{root}/chat/completions", headers, body


def extract_chat_text(data: Any, api_format: str = API_FORMAT_CHAT_COMPLETIONS) -> str:
    """Extract plain text from each supported provider response shape."""
    protocol = normalize_api_format(api_format)
    if not isinstance(data, dict):
        raise ValueError("LLM response must be an object")

    if protocol == API_FORMAT_ANTHROPIC_MESSAGES:
        blocks = data.get("content", [])
        if isinstance(blocks, str):
            return blocks
        if not isinstance(blocks, list):
            raise ValueError("Anthropic response content is invalid")
        text = "".join(
            block["text"]
            for block in blocks
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
        if not text:
            raise ValueError("Anthropic response contains no text")
        return text

    if protocol == API_FORMAT_OPENAI_RESPONSES:
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text:
            return output_text
        output = data.get("output", [])
        if not isinstance(output, list):
            raise ValueError("Responses output is invalid")
        chunks: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    chunks.append(block["text"])
        text = "".join(chunks)
        if not text:
            raise ValueError("Responses output contains no text")
        return text

    try:
        msg = data["choices"][0]["message"]
        content = msg.get("content")
        if content is None:
            # Reasoning models (e.g. DeepSeek-R1) may put output in reasoning_content
            # or return null content when all tokens were spent in reasoning.
            content = msg.get("reasoning_content") or msg.get("reasoning") or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Chat Completions response is invalid") from exc
    if not isinstance(content, str):
        raise ValueError("Chat Completions response content is invalid")
    return content


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
    """Chat client for the supported OpenAI, Anthropic, and Responses protocols."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        api_format: str | None = None,
    ) -> None:
        self.base_url = base_url or os.environ.get(
            "MEMORIA_LLM_BASE_URL", "https://api.openai.com/v1"
        )
        self.api_key = api_key or os.environ.get("MEMORIA_LLM_API_KEY", "")
        self.model = model or os.environ.get("MEMORIA_LLM_MODEL", "gpt-4o-mini")
        self.api_format = normalize_api_format(
            api_format or os.environ.get("MEMORIA_LLM_API_FORMAT")
        )

    def chat(self, system: str, user: str) -> str:
        url, headers, json_body = build_chat_request(
            self.base_url,
            self.api_key,
            self.model,
            self.api_format,
            system=system,
            user=user,
        )
        resp = safe_request(
            url,
            method="POST",
            headers=headers,
            json_body=json_body,
            timeout=120,
            max_bytes=4 * 1024 * 1024,
        )
        resp.raise_for_status()
        return extract_chat_text(resp.json(), self.api_format)

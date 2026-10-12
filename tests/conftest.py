"""Shared offline test doubles. Everything here is injected, never networked."""

from __future__ import annotations


class ScriptedChat:
    """Reply in call order; records prompts. Repeats the last reply once exhausted."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def chat(self, system, user):
        self.calls.append((system, user))
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]

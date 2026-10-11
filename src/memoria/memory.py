"""Minimal agent memory layer (feat-071) — bounded, editable, forgettable.

Design: docs/PERSONAL_AGENT_UPGRADE.md §3 P1.4 (D8). Memories hold user
preference/fact-type content that is neither wiki knowledge (cited, compiled)
nor conversation history (ephemeral). Deliberately minimal: no background
nudge/curator loop, no cross-system sync — injection into the qa prompt is the
only consumer (see graph/nodes.make_qa, which labels the block as data-only).
"""

from __future__ import annotations

import hashlib

from memoria.records import RecordStore

KIND = "memory"
MAX_ITEMS = 100


class MemoryLimitError(Exception):
    """Bounded by design: at the cap, remembering requires forgetting first."""


def memory_id_for(text: str) -> str:
    """Content-hash identity: dedup key at creation, row id thereafter."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:32]


class MemoryService:
    def __init__(self, records: RecordStore, max_items: int = MAX_ITEMS):
        self._records = records
        self._max_items = max_items

    def list(self) -> list[dict]:
        return self._records.scan(KIND)  # newest first

    def remember(self, text: str, source: str) -> tuple[dict, bool]:
        """Adds a memory; content-hash dedup returns the existing row.

        Returns (memory, created) — `created` comes straight from the row
        insert, so "already existed" is never guessed."""
        text = text.strip()
        if not text:
            raise ValueError("记忆内容不能为空")
        memory_id = memory_id_for(text)
        existing = self._records.get(KIND, memory_id)
        if existing:
            return existing, False
        if len(self.list()) >= self._max_items:
            raise MemoryLimitError(
                f"记忆已达上限（{self._max_items} 条），请先遗忘旧条目再添加"
            )
        data = {
            "id": memory_id,
            "text": text,
            "source": source,
            "created_at": _now_iso(),
        }
        created = self._records.insert(KIND, memory_id, data)
        return self._records.get(KIND, memory_id), created

    def edit(self, memory_id: str, new_text: str) -> dict | None:
        """CAS edit: the read premise is the stored text, so a concurrent edit
        loses cleanly instead of silently overwriting."""
        new_text = new_text.strip()
        if not new_text:
            raise ValueError("记忆内容不能为空")
        row = self._records.get(KIND, memory_id)
        if row is None:
            return None
        ok = self._records.cas(KIND, memory_id, {"text": row["text"]}, {"text": new_text})
        return self._records.get(KIND, memory_id) if ok else None

    def forget(self, memory_id: str) -> dict | None:
        """Atomic remove-and-return; nothing soft-deleted, nothing recoverable."""
        return self._records.take(KIND, memory_id)

    def all_for_prompt(self) -> list[dict]:
        return [{"text": m["text"], "source": m["source"]} for m in self.list()]


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()

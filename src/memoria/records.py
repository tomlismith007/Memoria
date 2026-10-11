"""Single-table record store: proposals (feat-066), later tasks/memories/notifications.

Design from OpenMuse (docs/agent-architecture/04b §3.2): everything is a row in one
`records(kind, id, data)` table; all concurrency control is a compare-and-set whose
premise (the fields the caller read) is re-checked before the write lands.

# ponytail: the read-check-write runs under a process lock instead of a single
conditional SQL statement. That is atomic for Memoria's deployment (one process,
one connection — the same assumption SqliteSaver already makes). A second writer
process would need the WHERE-clause variant (SQLite json_extract conditions) —
note that json_patch is RFC 7396 merge-patch, where a null patch value DELETES
the key, which silently drops fields like `result: {"raw_removed": None}`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path


class RecordStore:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS records ("
                "kind TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,"
                "PRIMARY KEY (kind, id))"
            )
            self._conn.commit()

    def insert(self, kind: str, rec_id: str, data: dict) -> bool:
        """Inserts a row; returns False when (kind, id) already exists."""
        payload = dict(data)
        payload["id"] = rec_id
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO records (kind, id, data) VALUES (?, ?, ?)",
                (kind, rec_id, json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def get(self, kind: str, rec_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT data FROM records WHERE kind = ? AND id = ?", (kind, rec_id)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def scan(self, kind: str) -> list[dict]:
        """All rows of a kind, newest first (insertion order via rowid)."""
        rows = self._conn.execute(
            "SELECT data FROM records WHERE kind = ? ORDER BY rowid DESC", (kind,)
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def cas(self, kind: str, rec_id: str, expected: dict, patch: dict) -> bool:
        """Conditional shallow-merge update: succeeds only when every field in
        `expected` still equals the stored value — the caller's read premise.
        Patch keys overwrite (including with None); unlisted keys are kept.
        Returns False when the premise changed (another writer won the race)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM records WHERE kind = ? AND id = ?", (kind, rec_id)
            ).fetchone()
            if row is None:
                return False
            data = json.loads(row[0])
            if any(data.get(k) != v for k, v in expected.items()):
                return False
            data.update(patch)
            cur = self._conn.execute(
                "UPDATE records SET data = ? WHERE kind = ? AND id = ?",
                (json.dumps(data, ensure_ascii=False), kind, rec_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

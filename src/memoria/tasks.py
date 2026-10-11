"""Minimal durable task engine (feat-068) — OpenMuse's at-most-once recipe,
single-process edition. Design: docs/PERSONAL_AGENT_UPGRADE.md §3 P1.1.

- One `records(kind="task")` row per task kind; mail_triage is a singleton that
  re-schedules itself after every run.
- at-most-once: `next_run_at` advances atomically with the claim, so a crash
  between execute and re-schedule cannot double-fire.
- recovery = replay: handlers are idempotent (archive proposals dedupe by
  idem_key, notifications by key), so a re-claimed task simply runs again.
- A heartbeat renews the lease during long handlers; an expired lease is
  re-claimable, which is what makes post-crash recovery work.

明确不做（指南 §4.4）：分布式 worker、消息队列、websocket、monitor/digest kind
（TASK_KINDS 之外仅留枚举位，不实现）。
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from datetime import datetime, timedelta, timezone

from memoria.records import RecordStore

KIND_TASK = "task"
KIND_NOTIFICATION = "notification"
TASK_KINDS = ("mail_triage",)  # "monitor" / "digest" reserved — do not implement
LEASE_SECONDS = 60

TERMINAL_OK = "scheduled"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def notify(
    records: RecordStore, key: str, title: str, body: str, link: str | None = None
) -> bool:
    """Append-only idempotent inbox: one record per key, mark-read only.

    The key encodes its own dedup scope (e.g. attempts for re-reminders) —
    callers who want a reminder on every retry put the attempt number in it.
    """
    nid = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    created = records.insert(
        KIND_NOTIFICATION,
        nid,
        {"key": key, "title": title, "body": body, "link": link, "read": False, "created_at": _iso(_now())},
    )
    return created


class TaskEngine:
    def __init__(
        self,
        records: RecordStore,
        handlers: dict,
        *,
        poll_seconds: float = 1.0,
        lease_seconds: int = LEASE_SECONDS,
    ):
        self._records = records
        self._handlers = handlers
        self._poll_seconds = poll_seconds
        self._lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- task lifecycle -----------------------------------------------------

    def ensure_task(self, kind: str, interval_seconds: int, payload: dict | None = None) -> dict:
        """Get-or-create the singleton scheduled task for `kind`."""
        if kind not in TASK_KINDS:
            raise ValueError(f"未知的任务类型: {kind}")
        existing = self.get_task(kind)
        if existing:
            return existing
        data = {
            "id": kind,  # one row per kind: the id IS the kind
            "kind": kind,
            "status": "scheduled",
            "interval_seconds": interval_seconds,
            "next_run_at": _iso(_now()),  # fire on the first tick
            "attempts": 0,
            "lease_id": None,
            "lease_until": None,
            "last_run_at": None,
            "last_result": None,
            "last_error": None,
            "payload": payload or {},
        }
        self._records.insert(KIND_TASK, kind, data)
        return self.get_task(kind)

    def get_task(self, kind: str) -> dict | None:
        return self._records.get(KIND_TASK, kind)

    def list_tasks(self) -> list[dict]:
        return self._records.scan(KIND_TASK)

    def list_notifications(self, unread_only: bool = False) -> list[dict]:
        items = self._records.scan(KIND_NOTIFICATION)
        return [n for n in items if not unread_only or not n.get("read")]

    def mark_notification_read(self, notification_id: str) -> dict | None:
        """CAS read False→True; append-only means there is no delete."""
        ok = self._records.cas(
            KIND_NOTIFICATION, notification_id, {"read": False}, {"read": True}
        )
        return self._records.get(KIND_NOTIFICATION, notification_id) if ok else None

    # -- scheduling (at-most-once) ------------------------------------------

    def _claim_for_fire(self, task: dict) -> dict | None:
        """Claims a due task and advances next_run_at in the SAME CAS — the
        schedule moves before execution, so a crash mid-run can only cost that
        one slot, never double-fire it."""
        now = _now()
        lease_until = _iso(now + timedelta(seconds=self._lease_seconds))
        patch = {
            "status": "running",
            "lease_id": uuid.uuid4().hex,
            "lease_until": lease_until,
            "next_run_at": _iso(now + timedelta(seconds=task.get("interval_seconds", 1800))),
        }
        for premise in ("scheduled", "queued"):
            if self._records.cas(KIND_TASK, task["id"], {"status": premise}, patch):
                return self._records.get(KIND_TASK, task["id"])
        return None  # someone else claimed it / not due anymore

    def _reclaim_expired(self, task: dict) -> dict | None:
        """Crash recovery: a running task whose lease expired is re-claimable."""
        now = _now()
        lease_until = task.get("lease_until")
        if not lease_until or _parse(lease_until) > now:
            return None
        patch = {
            "status": "running",
            "lease_id": uuid.uuid4().hex,
            "lease_until": _iso(now + timedelta(seconds=self._lease_seconds)),
        }
        if self._records.cas(
            KIND_TASK,
            task["id"],
            {"status": "running", "lease_id": task.get("lease_id")},
            patch,
        ):
            return self._records.get(KIND_TASK, task["id"])
        return None

    def tick(self) -> int:
        """Fires every due task once. Returns the number of executions."""
        fired = 0
        for task in self.list_tasks():
            claimed = None
            if task["status"] == "running":
                claimed = self._reclaim_expired(task)
            else:
                due = task.get("next_run_at")
                if due and _parse(due) <= _now():
                    claimed = self._claim_for_fire(task)
            if claimed:
                self._execute(claimed)
                fired += 1
        return fired

    def _execute(self, task: dict) -> None:
        lease_id = task["lease_id"]
        handler = self._handlers[task["kind"]]
        stop = threading.Event()

        def heartbeat() -> None:
            interval = max(1.0, self._lease_seconds / 3)
            while not stop.wait(interval):
                self._records.cas(
                    KIND_TASK,
                    task["id"],
                    {"status": "running", "lease_id": lease_id},
                    {"lease_until": _iso(_now() + timedelta(seconds=self._lease_seconds))},
                )

        watchdog = threading.Thread(target=heartbeat, daemon=True)
        watchdog.start()
        try:
            outcome = handler(task)
            error = None
        except Exception as e:
            outcome, error = None, str(e)[:200]
        finally:
            stop.set()
            watchdog.join(timeout=5)

        attempts = task.get("attempts", 0) + (1 if error else 0)
        patch = {
            "status": TERMINAL_OK,
            "attempts": attempts,
            "last_run_at": _iso(_now()),
            "last_result": outcome if not error else None,
            "last_error": error,
        }
        self._records.cas(
            KIND_TASK, task["id"], {"status": "running", "lease_id": lease_id}, patch
        )
        if error:
            # attempts in the key: every consecutive failure may notify again.
            notify(
                self._records,
                f"task-error:{task['id']}:{attempts}",
                f"定时任务 {task['kind']} 失败（第 {attempts} 次）",
                error,
                link=task["id"],
            )

    # -- loop ---------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="memoria-tasks")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self._poll_seconds):
            try:
                self.tick()
            except Exception:
                pass  # a bad tick must never kill the loop

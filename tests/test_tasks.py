"""feat-068: durable task engine — at-most-once, replay recovery, notification
inbox. 100% offline: handlers are fakes, ticks are manual (no loop thread)."""

import pytest

from memoria.proposals import ProposalService
from memoria.records import RecordStore
from memoria.tasks import TaskEngine, notify


@pytest.fixture
def records(tmp_path):
    return RecordStore(tmp_path / "records.db")


def _engine(records, handler, **kw):
    return TaskEngine(records, {"mail_triage": handler}, **kw)


def test_ensure_task_is_a_singleton_per_kind(records):
    eng = _engine(records, lambda task: {})
    t1 = eng.ensure_task("mail_triage", interval_seconds=1800)
    t2 = eng.ensure_task("mail_triage", interval_seconds=1800)
    assert t1["id"] == t2["id"] == "mail_triage"
    assert t1["status"] == "scheduled" and t1["attempts"] == 0


def test_ensure_task_rejects_unimplemented_kinds(records):
    eng = _engine(records, lambda task: {})
    with pytest.raises(ValueError):
        eng.ensure_task("monitor", interval_seconds=60)  # reserved, not implemented


def test_tick_fires_due_task_and_advances_next_run_at(records):
    calls = []
    eng = _engine(records, lambda task: calls.append(task["id"]))
    eng.ensure_task("mail_triage", interval_seconds=1800)
    assert eng.tick() == 1  # fresh task fires on the first tick
    assert calls == ["mail_triage"]
    task = eng.get_task("mail_triage")
    assert task["status"] == "scheduled"
    # at-most-once: next_run_at already moved past the run (not left in the past)
    from datetime import datetime, timezone
    assert datetime.fromisoformat(task["next_run_at"]) > datetime.now(timezone.utc)
    assert eng.tick() == 0  # not due again


def test_crash_records_failure_and_notifies_per_attempt(records):
    flaky = {"count": 0}

    def handler(task):
        flaky["count"] += 1
        raise RuntimeError("gmail died")

    eng = _engine(records, handler)
    eng.ensure_task("mail_triage", interval_seconds=1800)
    eng.tick()
    task = eng.get_task("mail_triage")
    assert task["status"] == "scheduled" and task["attempts"] == 1
    assert "gmail died" in task["last_error"]

    # at-most-once: the failed slot is already consumed (next_run_at advanced at
    # claim) — the retry happens at the NEXT interval, so force it due.
    eng._records.cas(
        "task", "mail_triage", {"status": "scheduled"}, {"next_run_at": "2000-01-01T00:00:00+00:00"}
    )
    eng.tick()
    task = eng.get_task("mail_triage")
    assert task["attempts"] == 2
    notes = eng.list_notifications()
    keys = {n["key"] for n in notes}
    assert keys == {"task-error:mail_triage:1", "task-error:mail_triage:2"}


def test_recovery_is_replay_via_idempotent_handler(records):
    """Crash mid-run → lease expires → tick re-claims → handler reruns; the
    idem key makes the second run return the SAME proposal (no duplicates)."""
    proposals = ProposalService(records)
    runs = {"count": 0}

    def handler(task):
        runs["count"] += 1
        if runs["count"] == 1:
            proposals.propose("archive", {"thread_id": "t"}, idem_key="archive:auto:abc")
            raise RuntimeError("crash after propose")  # died before completing
        return {"pending": 1}

    eng = _engine(records, handler)
    eng.ensure_task("mail_triage", interval_seconds=1800)
    eng.tick()  # crash run
    assert eng.get_task("mail_triage")["attempts"] == 1

    # simulate lease expiry so the task is immediately re-claimable
    eng._records.cas(
        "task", "mail_triage", {"status": "scheduled"}, {"next_run_at": "2000-01-01T00:00:00+00:00"}
    )
    eng.tick()
    assert runs["count"] == 2
    proposals_list = proposals.list()
    assert len(proposals_list) == 1  # idem key deduped the replay
    assert proposals_list[0]["payload"] == {"thread_id": "t"}


def test_expired_lease_is_reclaimable(records):
    eng = _engine(records, lambda task: None)
    eng.ensure_task("mail_triage", interval_seconds=1800)
    eng.tick()
    # Pretend the process died mid-run: running with a stale lease.
    eng._records.cas(
        "task",
        "mail_triage",
        {"status": "scheduled"},
        {
            "status": "running",
            "lease_id": "ghost",
            "lease_until": "2000-01-01T00:00:00+00:00",
        },
    )
    assert eng.tick() == 1  # recovered by replay
    assert eng.get_task("mail_triage")["status"] == "scheduled"


def test_notification_inbox_is_append_only_and_mark_read_only(records):
    assert notify(records, "k1", "标题", "内容") is True
    assert notify(records, "k1", "标题", "内容") is False  # same key: deduped
    eng = TaskEngine(records, {})
    notes = eng.list_notifications(unread_only=True)
    assert len(notes) == 1
    read = eng.mark_notification_read(notes[0]["id"])
    assert read["read"] is True
    assert eng.list_notifications(unread_only=True) == []
    assert eng.mark_notification_read(notes[0]["id"]) is None  # no undo, no delete


def test_web_exposes_tasks_and_notification_endpoints(tmp_path):
    """feat-068: injected engine surfaces /api/tasks + the notification inbox."""
    from langgraph.checkpoint.memory import MemorySaver
    from starlette.testclient import TestClient

    from memoria.llm import FakeChat
    from memoria.rag import ChromaStore, FakeEmbedder
    from memoria.web.app import create_app
    from memoria.wiki import Wiki

    records = RecordStore(tmp_path / "records.db")
    engine = TaskEngine(records, {"mail_triage": lambda task: {"pending": 0}})
    engine.ensure_task("mail_triage", interval_seconds=1800)
    engine.stop()  # injected for endpoint testing; no loop thread

    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    app = create_app(
        {
            "store": ChromaStore(path=str(tmp_path / "chroma")),
            "embedder": FakeEmbedder(),
            "llm": FakeChat("ok"),
            "wiki": wiki,
            "emails": [],
            "checkpointer": MemorySaver(),
            "records": records,
            "task_engine": engine,
            "mail_service": object(),  # ready by construction; engine wiring skipped
        }
    )
    client = TestClient(app)

    tasks = client.get("/api/tasks").json()["tasks"]
    assert len(tasks) == 1 and tasks[0]["id"] == "mail_triage"
    assert tasks[0]["status"] == "scheduled"

    assert client.get("/api/notifications").json()["notifications"] == []
    notify(records, "web-test", "运行失败", "伪造错误", link="mail_triage")
    unread = client.get("/api/notifications?unread=true").json()["notifications"]
    assert len(unread) == 1 and unread[0]["title"] == "运行失败"

    resp = client.post(f"/api/notifications/{unread[0]['id']}/read")
    assert resp.status_code == 200 and resp.json()["notification"]["read"] is True
    assert client.get("/api/notifications?unread=true").json()["notifications"] == []
    missing = client.post("/api/notifications/nonexistent/read")
    assert missing.status_code == 404

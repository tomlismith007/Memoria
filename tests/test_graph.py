"""feat-007: graph routing + interrupt confirm. Offline — stubs, MemorySaver."""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from memoria.graph import build_graph
from memoria.mail import Email
from memoria.rag import ChromaStore, FakeEmbedder, ingest_document
from memoria.wiki import Wiki


class ScriptedChat:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, system, user):
        self.calls.append((system, user))
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]


class StubService:
    """Duck-typed Gmail service: list/get one marketing mail, modify archives it."""

    FULL = {
        "id": "m4",
        "snippet": "全场三折",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "限时优惠"},
                {"name": "From", "value": "promo@x.com"},
            ]
        },
    }

    def __init__(self):
        self.archived = []
        self._op = None

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kw):
        self._op = ("list", kw)
        return self

    def get(self, **kw):
        self._op = ("get", kw)
        return self

    def modify(self, **kw):
        self._op = ("modify", kw)
        return self

    def execute(self):
        kind, kw = self._op
        if kind == "list":
            return {"messages": [{"id": "m4"}]}
        if kind == "get":
            return dict(self.FULL)
        self.archived.append(kw["id"])
        return {}


def _kb(tmp_path):
    store = ChromaStore(path=str(tmp_path / "chroma"))
    src = tmp_path / "note.md"
    src.write_text("服务 A 将于 2027-01-01 到期，请提前续费。" * 10, encoding="utf-8")
    ingest_document(str(src), store, FakeEmbedder(), chunk_size=60, chunk_overlap=5)
    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    return store, wiki


def test_qa_route(tmp_path):
    store, wiki = _kb(tmp_path)
    llm = ScriptedChat("问答", "服务 A 2027 年到期。[1]")
    g = build_graph(store, FakeEmbedder(), llm, wiki).compile()
    out = g.invoke({"text": "服务 A 何时到期"})
    assert out["intent"] == "问答"
    assert "2027" in out["answer_text"]
    assert out["answer_citations"][0].doc_id  # citation survived the graph


def test_router_fallback_to_qa(tmp_path):
    store, wiki = _kb(tmp_path)
    llm = ScriptedChat("听不懂", "答案。[1]")
    g = build_graph(store, FakeEmbedder(), llm, wiki).compile()
    out = g.invoke({"text": "??? "})
    assert out["intent"] == "问答"


def test_mail_route_pauses_for_human(tmp_path):
    store, wiki = _kb(tmp_path)
    svc = StubService()
    llm = ScriptedChat("邮件", "类别：营销\n摘要：促销广告。")
    g = build_graph(store, FakeEmbedder(), llm, wiki, mail_service=svc).compile(
        checkpointer=MemorySaver()
    )
    cfg = {"configurable": {"thread_id": "t1"}}
    g.invoke({"text": "看看邮件"}, cfg)

    snap = g.get_state(cfg)
    interrupts = [i for t in snap.tasks for i in (t.interrupts or [])]
    assert len(interrupts) == 1  # graph paused: no archive without a human
    assert interrupts[0].value == {"pending_archive": ["m4"]}
    assert svc.archived == []

    g.invoke(Command(resume={"approved": ["m4"]}), cfg)  # human clicks confirm
    final = g.get_state(cfg)
    assert final.values["confirmed_ids"] == ["m4"]
    assert final.values["archived"] == ["m4"]
    assert svc.archived == ["m4"]


def test_mail_route_reject_leaves_inbox(tmp_path):
    store, wiki = _kb(tmp_path)
    svc = StubService()
    llm = ScriptedChat("邮件", "类别：营销\n摘要：促销广告。")
    g = build_graph(store, FakeEmbedder(), llm, wiki, mail_service=svc).compile(
        checkpointer=MemorySaver()
    )
    cfg = {"configurable": {"thread_id": "t2"}}
    g.invoke({"text": "看看邮件"}, cfg)
    g.invoke(Command(resume={"approved": []}), cfg)  # human rejects
    final = g.get_state(cfg)
    assert final.values["archived"] == []
    assert svc.archived == []


def test_ingest_route_multistep(tmp_path):
    store, wiki = _kb(tmp_path)
    llm = ScriptedChat("ingest", "## [[服务到期]]\n# 服务到期\n\n2027 年到期。\n")
    g = build_graph(store, FakeEmbedder(), llm, wiki).compile()
    out = g.invoke({"text": "记一条", "material": "服务 A 2027 年到期", "origin": "raw/x.txt"})
    assert out["intent"] == "ingest"
    assert out["ingest_updated"] == ["服务到期"]  # read -> wrote pages
    assert "[[服务到期]]" in (wiki.read_page("index") or "")  # index updated
    assert out["lint_broken"] == [] and out["lint_orphans"] == ["服务到期"]  # lint ran

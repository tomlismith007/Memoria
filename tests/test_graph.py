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


def test_qa_route_wiki_sufficient_and_router_skipped(tmp_path):
    store, wiki = _kb(tmp_path)
    wiki.write_page("服务到期", "# 服务到期\n\n2027 年到期。\n")
    wiki.build_index()
    llm = ScriptedChat("[[服务到期]]", "服务 A 2027 年到期。[[服务到期]]", "充分")
    g = build_graph(store, FakeEmbedder(), llm, wiki).compile()
    out = g.invoke({"text": "服务 A 何时到期", "intent": "问答"})
    assert out["answer_source"] == "wiki"
    assert out["answer_verified"] is True
    assert "意图路由" not in llm.calls[0][0]  # preset intent skipped the router LLM


def test_ingest_route_source_path_dual_writes(tmp_path):
    store, wiki = _kb(tmp_path)
    src = tmp_path / "raw-note.md"
    src.write_text("服务 A 2027 年到期，请及时续费。" * 5, encoding="utf-8")
    llm = ScriptedChat("## [[服务到期]]\n# 服务到期\n\n2027 年到期。\n")
    g = build_graph(store, FakeEmbedder(), llm, wiki).compile()
    out = g.invoke(
        {"intent": "ingest", "source_path": str(src), "origin": "raw-note.md"}
    )
    assert out["doc_id"] and out["chunks"] > 0
    assert store.count() > 0  # vectors written through the graph (feat-008 dual write)
    assert out["ingest_updated"] == ["服务到期"]


def test_qa_route_carries_history_for_follow_ups(tmp_path):
    store, wiki = _kb(tmp_path)
    llm = ScriptedChat("[[不存在的页]]", "无相关页面。", "补充", "2027 年到期。[1]")
    g = build_graph(store, FakeEmbedder(), llm, wiki).compile(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "conv-1"}}
    first = g.invoke({"text": "服务 A 何时到期", "intent": "问答"}, cfg)
    assert first["history"][0]["question"] == "服务 A 何时到期"

    n_first = len(llm.calls)
    follow = g.invoke({"text": "那需要提前多久续费？", "intent": "问答"}, cfg)
    recent = "\n".join(u for _, u in llm.calls[n_first:])
    assert "服务 A 何时到期" in recent  # prior turn reached the follow-up prompts
    assert "那需要提前多久续费" in recent
    assert len(follow["history"]) == 2  # turn appended, not replaced


def test_recent_turns_drops_oldest_until_budget_fits():
    """feat-042: history is trimmed by token budget, newest turns kept first."""
    from memoria.graph.nodes import KEEP_RECENT_TOKENS, _recent_turns

    def turn(i, size):
        return {"question": f"q{i}", "answer": "答" * size}

    # Each turn costs (2 + 6000) / 1.5 ≈ 4001.3 tokens, so 4 fit and a 5th would exceed.
    history = [turn(i, 6000) for i in range(10)]
    kept = _recent_turns(history)
    assert len(kept) == 4
    assert kept[-1]["question"] == "q9"  # newest survives
    assert kept[0]["question"] == "q6"  # the six oldest are dropped

    # The kept turns must actually fit the budget they claim to respect.
    total = sum(len(t["question"]) + len(t["answer"]) for t in kept) / 1.5
    assert total <= KEEP_RECENT_TOKENS

    # A short history is never truncated.
    short = [turn(i, 10) for i in range(3)]
    assert _recent_turns(short) == short

    # Empty history is safe.
    assert _recent_turns([]) == []


def test_llm_nodes_retry_transient_failures(tmp_path):
    store, wiki = _kb(tmp_path)

    class FlakyChat:
        """Fails twice with a transient gateway error, then answers normally."""

        def __init__(self):
            self.calls = 0

        def chat(self, system, user):
            self.calls += 1
            if self.calls <= 2:
                raise ConnectionError("gateway hiccup")
            return "## [[服务到期]]\n# 服务到期\n\n2027 年到期。\n"

    llm = FlakyChat()
    g = build_graph(store, FakeEmbedder(), llm, wiki).compile()
    out = g.invoke(
        {"intent": "ingest", "material": "服务 A 2027 年到期", "origin": "raw/x.txt"}
    )
    assert out["ingest_updated"] == ["服务到期"]
    assert llm.calls == 3  # two transient failures retried, third attempt landed


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

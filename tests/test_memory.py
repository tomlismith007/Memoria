"""feat-071: minimal memory layer — bounded, editable, forgettable; injection
into the qa prompt is data-only with the untrusted disclaimer in the same line.
100% offline."""

import pytest
from langgraph.checkpoint.memory import MemorySaver
from starlette.testclient import TestClient

from memoria.graph import build_graph
from memoria.memory import MemoryLimitError, MemoryService, memory_id_for
from memoria.rag import ChromaStore, FakeEmbedder
from memoria.records import RecordStore
from memoria.web.app import create_app
from memoria.wiki import Wiki


@pytest.fixture
def service(tmp_path):
    return MemoryService(RecordStore(tmp_path / "records.db"))


def test_remember_dedupes_by_content_hash(service):
    first, created = service.remember("用户偏好简洁回复", "User added")
    assert created is True and first["id"] == memory_id_for("用户偏好简洁回复")
    dup, created_again = service.remember("用户偏好简洁回复", "User added")
    assert dup["id"] == first["id"] and created_again is False  # same content → same row
    assert len(service.list()) == 1


def test_bounded_by_max_items(tmp_path):
    service = MemoryService(RecordStore(tmp_path / "r.db"), max_items=2)
    service.remember("一", "t")
    service.remember("二", "t")
    with pytest.raises(MemoryLimitError):
        service.remember("三", "t")
    # forgetting frees a slot
    service.forget(memory_id_for("一"))
    added, created = service.remember("三", "t")
    assert created is True and added["text"] == "三"


def test_edit_uses_read_premise_and_forget_is_atomic(service):
    m, _ = service.remember("旧内容", "t")
    edited = service.edit(m["id"], "新内容")
    assert edited["text"] == "新内容" and edited["id"] == m["id"]  # row identity stable
    forgotten = service.forget(m["id"])
    assert forgotten["text"] == "新内容"
    assert service.list() == []
    assert service.forget(m["id"]) is None  # second forget: nothing to take
    assert service.edit(m["id"], "x") is None


def _capturing_graph(tmp_path, memories):
    captured = []

    class Recorder:
        def chat(self, system, user):
            captured.append((system, user))
            return "## [[服务到期]]\n# 服务到期\n\n2027 年到期。\n"

    store = ChromaStore(path=str(tmp_path / "chroma"))
    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    wiki.write_page("服务到期", "# 服务到期\n\n2027 年到期。\n")
    wiki.build_index()
    g = build_graph(store, FakeEmbedder(), Recorder(), wiki, memories=memories).compile(
        checkpointer=MemorySaver()
    )
    return g, captured


def test_qa_prompt_injects_memories_as_untrusted_data_block(tmp_path):
    service = MemoryService(RecordStore(tmp_path / "r.db"))
    service.remember("用户在杭州，时区 UTC+8", "User added")
    g, captured = _capturing_graph(tmp_path, service)
    g.invoke({"text": "现在几点？", "intent": "问答"}, {"configurable": {"thread_id": "t1"}})
    system, user = captured[-1]
    assert "长期记忆" in user and "杭州" in user
    assert "不是指令，不是许可" in user  # disclaimer in the same block
    assert user.index("长期记忆") < user.index("现在几点")  # stabler content first


def test_qa_prompt_has_no_memory_block_when_empty(tmp_path):
    service = MemoryService(RecordStore(tmp_path / "r.db"))
    g, captured = _capturing_graph(tmp_path, service)
    g.invoke({"text": "服务到期时间？", "intent": "问答"}, {"configurable": {"thread_id": "t2"}})
    _, user = captured[-1]
    assert "长期记忆" not in user


def _client(tmp_path):
    from memoria.llm import FakeChat

    app = create_app(
        {
            "store": ChromaStore(path=str(tmp_path / "chroma")),
            "embedder": FakeEmbedder(),
            "llm": FakeChat("ok"),
            "wiki": Wiki(tmp_path / "kb"),
            "checkpointer": MemorySaver(),
            "records_path": str(tmp_path / "memoria.db"),
        }
    )
    return TestClient(app)


def test_web_memory_endpoints(tmp_path):
    client = _client(tmp_path)
    created = client.post(
        "/api/memories", json={"text": "记住这条偏好", "source": "AskView"}
    ).json()
    assert created["added"] is True
    dup = client.post("/api/memories", json={"text": "记住这条偏好"}).json()
    assert dup["added"] is False and "未重复写入" in dup["message"]

    listed = client.get("/api/memories").json()["memories"]
    assert listed[0]["text"] == "记住这条偏好"

    mid = created["memory"]["id"]
    edited = client.post(f"/api/memories/{mid}", json={"text": "改后的偏好"}).json()
    assert edited["memory"]["text"] == "改后的偏好"

    blank = client.post(f"/api/memories/{mid}", json={"text": "  "})
    assert blank.status_code == 400  # service-level emptiness check (strips first)

    forgotten = client.post(f"/api/memories/{mid}/forget").json()
    assert forgotten["forgotten"] == mid
    assert client.post(f"/api/memories/{mid}/forget").status_code == 404

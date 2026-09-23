"""feat-003: hybrid retrieval + cited answering. Offline — stubs and fakes only."""

from memoria.llm import FakeChat, OpenAICompatibleChat
from memoria.rag import (
    ChromaStore,
    FakeEmbedder,
    answer,
    combined_score,
    ingest_document,
    keyword_score,
    retrieve,
)


class SameVectorEmbedder:
    """Returns an identical vector for every text: ranking falls back to keywords only."""

    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


def _write(path, body: str) -> str:
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_keyword_rerank_beats_vector_tie(tmp_path):
    store = ChromaStore(path=str(tmp_path / "chroma"))
    car = _write(tmp_path / "car.md", "汽车火车飞机轮船。交通工具介绍。" * 10)
    fruit = _write(tmp_path / "fruit.md", "苹果香蕉橙子葡萄。水果价格表。" * 10)
    ingest_document(car, store, SameVectorEmbedder(), chunk_size=60, chunk_overlap=5)
    ingest_document(fruit, store, SameVectorEmbedder(), chunk_size=60, chunk_overlap=5)

    hits = retrieve("苹果多少钱", store, SameVectorEmbedder(), k=8, top_n=4)
    assert hits, "must return hits"
    assert all("苹果" in h["text"] or "水果" in h["text"] for h in hits[:2])
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)  # ranked


def test_scores_bounded_and_keyword_pure():
    assert keyword_score("苹果 价格", "苹果今日价格") == 1.0
    assert keyword_score("苹果", "汽车介绍") == 0.0
    assert keyword_score("", "anything") == 0.0
    assert 0.0 <= combined_score(0.2, 0.5) <= 1.0
    assert combined_score(None, 1.0, alpha=0.0) == 1.0


def test_answer_maps_citations_to_real_chunks(tmp_path):
    store = ChromaStore(path=str(tmp_path / "chroma"))
    src = _write(tmp_path / "note.md", "服务 A 将于 2027-01-01 到期，请提前续费。" * 10)
    from memoria.rag import load_document

    doc_id = load_document(src).doc_id
    ingest_document(src, store, FakeEmbedder(), chunk_size=60, chunk_overlap=5)

    llm = FakeChat(reply="服务 A 将于 2027 年到期，请提前续费。[1]")
    ans = answer("服务 A 何时到期", store, FakeEmbedder(), llm, k=4, top_n=2)
    assert "[1]" in ans.text
    assert len(ans.citations) == 1
    c = ans.citations[0]
    assert (c.ref, c.doc_id) == (1, doc_id)  # citation resolves to the real doc/chunk
    assert "到期" in llm.calls[0][1]  # retrieved context was fed to the LLM


def test_answer_empty_store_skips_llm(tmp_path):
    store = ChromaStore(path=str(tmp_path / "chroma"))
    llm = FakeChat(reply="anything")
    ans = answer("随便问", store, FakeEmbedder(), llm)
    assert "无法回答" in ans.text
    assert ans.citations == []
    assert llm.calls == []  # no retrieval -> no LLM call, no hallucination


def test_answer_ignores_out_of_range_refs(tmp_path):
    store = ChromaStore(path=str(tmp_path / "chroma"))
    src = _write(tmp_path / "note.md", "有效内容。" * 20)
    ingest_document(src, store, FakeEmbedder(), chunk_size=50, chunk_overlap=5)
    llm = FakeChat(reply="胡说。[9]")  # hallucinated ref must be dropped
    ans = answer("问", store, FakeEmbedder(), llm, k=4, top_n=2)
    assert ans.citations == []


def test_chat_parses_response(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "你好"}}]}

    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, model=json["model"], roles=[m["role"] for m in json["messages"]])
        return FakeResp()

    monkeypatch.setattr("requests.post", fake_post)
    c = OpenAICompatibleChat(base_url="http://x", api_key="k", model="m")
    assert c.chat("sys", "hi") == "你好"
    assert seen == {"url": "http://x/chat/completions", "model": "m", "roles": ["system", "user"]}

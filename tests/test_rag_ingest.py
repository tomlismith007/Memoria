"""feat-002: ingest pipeline tests. Offline — FakeEmbedder + tmp Chroma, no keys, no network."""

import pytest

from memoria.net import SafeRequestError, SafeResponse
from memoria.rag import (
    ChromaStore,
    FakeEmbedder,
    OpenAICompatibleEmbedder,
    chunk_text,
    delete_document,
    ingest_document,
    load_document,
)


@pytest.fixture
def store(tmp_path):
    return ChromaStore(path=str(tmp_path / "chroma"))


@pytest.fixture
def embedder():
    return FakeEmbedder()


def _write_doc(path, body: str):
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_ingest_search_cites_source(tmp_path, store, embedder):
    src = _write_doc(
        tmp_path / "note.md",
        "# 服务到期\n\n服务 A 将于 2027-01-01 到期，请提前续费。\n\n# 其他\n\n今天天气不错，适合散步。",
    )
    result = ingest_document(src, store, embedder, chunk_size=30, chunk_overlap=5)
    assert result.chunks > 1

    query_vec = embedder.embed(["服务 A 什么时候到期"])[0]
    hits = store.search(query_vec, k=3)
    assert hits, "search must return hits"
    assert all(h["doc_id"] == result.doc_id for h in hits)  # every hit cites its doc
    assert any("到期" in h["text"] for h in hits)  # relevant chunk retrieved
    assert all({"chunk", "start"} <= set(h) for h in hits)  # chunk-level citation


def test_reingest_replaces_vectors_no_duplicates(tmp_path, store, embedder):
    src = _write_doc(tmp_path / "note.md", "版本一的内容。" * 20)
    first = ingest_document(src, store, embedder, chunk_size=50, chunk_overlap=5)
    n1 = store.count()
    second = ingest_document(src, store, embedder, chunk_size=50, chunk_overlap=5)
    assert second.doc_id == first.doc_id  # same origin -> same doc_id
    assert store.count() == n1  # re-ingest replaces, never duplicates


def test_delete_document_removes_all_vectors(tmp_path, store, embedder):
    src = _write_doc(tmp_path / "note.md", "待删除的内容。" * 20)
    result = ingest_document(src, store, embedder, chunk_size=50, chunk_overlap=5)
    assert store.count() > 0
    delete_document(result.doc_id, store)
    assert store.count() == 0  # red line: no orphan vectors


def test_chunk_offsets_cover_text():
    text = "abcdefghij" * 30
    chunks = chunk_text(text, size=100, overlap=20)
    assert chunks[0].start == 0
    assert chunks[-1].end == len(text)
    assert "".join(c.text for c in chunks[:1]) == text[:100]
    with pytest.raises(ValueError):
        chunk_text(text, size=50, overlap=50)


def test_load_document_rejects_local_web_url():
    with pytest.raises(SafeRequestError):
        load_document("http://localhost:8000/private")


def test_load_document_fetches_web_through_safe_request(monkeypatch):
    seen = {}

    def fake_request(url, method, timeout, max_bytes):
        seen.update(url=url, method=method, timeout=timeout, max_bytes=max_bytes)
        return SafeResponse(200, {}, "<html><script>x</script><p>安全正文</p></html>")

    monkeypatch.setattr("memoria.rag.parse.safe_request", fake_request)
    document = load_document("https://example.com/article")
    assert document.text == "安全正文"
    assert seen == {
        "url": "https://example.com/article",
        "method": "GET",
        "timeout": 30,
        "max_bytes": 5 * 1024 * 1024,
    }


def test_load_document_markdown_and_txt(tmp_path):
    md = _write_doc(tmp_path / "a.md", "# 标题\n\n正文")
    txt = _write_doc(tmp_path / "b.txt", "纯文本")
    assert load_document(md).text == "# 标题\n\n正文"
    assert load_document(txt).text == "纯文本"
    assert load_document(md).doc_id == load_document(md).doc_id  # stable per origin


def test_fake_embedder_deterministic():
    e = FakeEmbedder()
    assert e.embed(["你好世界"]) == e.embed(["你好世界"])
    assert e.embed(["a"]) != e.embed(["b"])


def test_openai_compat_embedder_parses_response(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"index": 1, "embedding": [0.2]}, {"index": 0, "embedding": [0.1]}]}

    calls = {}

    def fake_post(url, method, headers, json_body, timeout, max_bytes):
        calls.update(url=url, model=json_body["model"], n=len(json_body["input"]))
        return FakeResp()

    monkeypatch.setattr("memoria.rag.embed.safe_request", fake_post)
    e = OpenAICompatibleEmbedder(base_url="https://gateway.example/v1", api_key="k", model="m")
    assert e.embed(["a", "b"]) == [[0.1], [0.2]]  # sorted back into input order
    assert calls == {"url": "https://gateway.example/v1/embeddings", "model": "m", "n": 2}

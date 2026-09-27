"""feat-003: hybrid retrieval + cited answering. Offline — stubs and fakes only."""

import pytest

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
    assert ans.citations_verified is True


def test_answer_empty_store_skips_llm(tmp_path):
    store = ChromaStore(path=str(tmp_path / "chroma"))
    llm = FakeChat(reply="anything")
    ans = answer("随便问", store, FakeEmbedder(), llm)
    assert "无法回答" in ans.text
    assert ans.citations == []
    assert llm.calls == []  # no retrieval -> no LLM call, no hallucination
    assert ans.citations_verified is True  # refusal makes no claims to trace


def test_answer_flags_uncovered_sentences(tmp_path):
    store = ChromaStore(path=str(tmp_path / "chroma"))
    src = _write(tmp_path / "note.md", "服务 A 将于 2027-01-01 到期，请提前续费。" * 10)
    ingest_document(src, store, FakeEmbedder(), chunk_size=60, chunk_overlap=5)

    cases = [
        ("服务 A 2027 年到期。[1]", True),
        ("服务 A 2027 年到期。[1] 续费很便宜。", False),  # second sentence uncited
        ("胡说八道的内容。[9]", False),  # out-of-range ref is not a source
        ("第一句有据。[1]\n第二句裸奔。", False),  # newline-separated bullet must cite too
    ]
    for reply, expected in cases:
        ans = answer("服务 A 何时到期", store, FakeEmbedder(), FakeChat(reply=reply), k=4, top_n=2)
        assert ans.citations_verified is expected, reply


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

    def fake_post(url, method, headers, json_body, timeout, max_bytes):
        seen.update(url=url, model=json_body["model"], roles=[m["role"] for m in json_body["messages"]])
        return FakeResp()

    monkeypatch.setattr("memoria.llm.safe_request", fake_post)
    c = OpenAICompatibleChat(base_url="https://gateway.example/v1", api_key="k", model="m")
    assert c.chat("sys", "hi") == "你好"
    assert seen == {"url": "https://gateway.example/v1/chat/completions", "model": "m", "roles": ["system", "user"]}


@pytest.mark.parametrize(
    ("api_format", "response", "expected_text", "expected_url"),
    [
        (
            "chat_completions",
            {"choices": [{"message": {"content": "chat"}}]},
            "chat",
            "https://gateway.example/v1/chat/completions",
        ),
        (
            "anthropic_messages",
            {"content": [{"type": "text", "text": "claude"}]},
            "claude",
            "https://gateway.example/v1/messages",
        ),
        (
            "openai_responses",
            {"output": [{"content": [{"type": "output_text", "text": "responses"}]}]},
            "responses",
            "https://gateway.example/v1/responses",
        ),
    ],
)
def test_chat_protocols_build_provider_specific_requests(
    monkeypatch, api_format, response, expected_text, expected_url
):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return response

    seen = {}

    def fake_post(url, method, headers, json_body, timeout, max_bytes):
        seen.update(url=url, headers=headers, json_body=json_body)
        return FakeResp()

    monkeypatch.setattr("memoria.llm.safe_request", fake_post)
    client = OpenAICompatibleChat(
        base_url="https://gateway.example/v1",
        api_key="secret",
        model="model-x",
        api_format=api_format,
    )
    assert client.chat("system prompt", "hello") == expected_text
    assert seen["url"] == expected_url
    assert seen["json_body"]["model"] == "model-x"

    if api_format == "chat_completions":
        assert seen["headers"]["Authorization"] == "Bearer secret"
        assert [item["role"] for item in seen["json_body"]["messages"]] == ["system", "user"]
    elif api_format == "anthropic_messages":
        assert seen["headers"]["x-api-key"] == "secret"
        assert seen["headers"]["anthropic-version"] == "2023-06-01"
        assert seen["json_body"]["system"] == [
            {
                "type": "text",
                "text": "system prompt",
                "cache_control": {"type": "ephemeral"},
            }
        ]
        assert [item["role"] for item in seen["json_body"]["messages"]] == ["user"]
    else:
        assert seen["headers"]["Authorization"] == "Bearer secret"
        assert seen["json_body"]["instructions"] == "system prompt"
        assert seen["json_body"]["input"] == "hello"


def test_cache_marker_only_on_protocols_that_support_it():
    """feat-041: a compatible endpoint must never be handed an unknown cache field."""
    from memoria.llm import build_chat_request

    _, _, anthropic_body = build_chat_request(
        "https://api.anthropic.com",
        "k",
        "m",
        api_format="anthropic_messages",
        system="sys",
        user="hi",
    )
    assert anthropic_body["system"][0]["cache_control"] == {"type": "ephemeral"}

    # chat_completions keeps a plain string system: no marker is emitted, because
    # whether a given gateway honours prompt_cache_key is not something we can assume.
    _, _, chat_body = build_chat_request(
        "https://gw.example/v1",
        "k",
        "m",
        api_format="chat_completions",
        system="sys",
        user="hi",
    )
    assert chat_body["messages"][0] == {"role": "system", "content": "sys"}
    assert "cache_control" not in str(chat_body)

    _, _, responses_body = build_chat_request(
        "https://gw.example/v1",
        "k",
        "m",
        api_format="openai_responses",
        system="sys",
        user="hi",
    )
    assert responses_body["instructions"] == "sys"
    assert "cache_control" not in str(responses_body)


def test_anthropic_omits_system_block_when_empty():
    """No system prompt means no cache marker — the field must stay absent."""
    from memoria.llm import build_chat_request

    _, _, body = build_chat_request(
        "https://api.anthropic.com",
        "k",
        "m",
        api_format="anthropic_messages",
        system="",
        user="hi",
    )
    assert "system" not in body

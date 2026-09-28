"""Tests for feat-010/feat-033: Web API service (FastAPI), fully graph-backed. 100% offline."""

import re

import pytest
from langgraph.checkpoint.memory import MemorySaver
from starlette.testclient import TestClient

from memoria.mail import Email
from memoria.rag import ChromaStore, FakeEmbedder, ingest_document
from memoria.web.app import create_app
from memoria.wiki import Wiki


class SmartChat:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def chat(self, system, user):
        self.calls.append((system, user))
        if "意图路由" in system:
            # feat-045: /api/agent is the production path that exercises the router.
            return "问答"
        if "Wiki 维护者" in system or "更新相关页面" in user:
            return "## [[服务到期]]\n# 服务到期\n\n2027 到期。\n"
        if "Wiki 检索器" in system:
            return "[[服务到期]]"
        if "回答质检员" in system:
            return "充分"
        if "邮件分类助手" in system:
            # feat-043: the batch prompt numbers each mail, so answer per index.
            if re.search(r"^\[\d+\] 发件人：", user, re.M):
                out = []
                for m in re.finditer(
                    r"^\[(\d+)\] 发件人：.*?\n主题：(.*?)\n内容：(.*?)(?=\n\n\[|\Z)",
                    user,
                    re.M | re.S,
                ):
                    idx, subject = m.group(1), m.group(2)
                    if "优惠券" in subject or "年中大促" in subject:
                        out.append(f"[{idx}] 类别：营销\n[{idx}] 摘要：年中大促打折优惠")
                    else:
                        out.append(f"[{idx}] 类别：通知\n[{idx}] 摘要：验证码动态通知")
                return "\n".join(out)
            if "优惠券" in user or "年中大促" in user:
                return "类别：营销\n摘要：年中大促打折优惠"
            return "类别：通知\n摘要：验证码动态通知"
        return "服务 A 2027 年到期。[[服务到期]]"


@pytest.fixture
def api_client(tmp_path):
    store = ChromaStore(path=str(tmp_path / "chroma"))
    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    llm = SmartChat()
    emails = [
        Email(msg_id="m1", subject="【招行】您的验证码为 123456", sender="service@cmb.com", snippet="5 分钟内有效"),
        Email(msg_id="m2", subject="年中大促全场 5 折！", sender="promo@shop.com", snippet="点击领取优惠券"),
    ]
    app = create_app({
        "store": store,
        "embedder": FakeEmbedder(),
        "llm": llm,
        "wiki": wiki,
        "emails": emails,
        "checkpointer": MemorySaver(),
    })
    return TestClient(app), wiki, store


def test_health(api_client):
    client, _, _ = api_client
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    # feat-047: status stays "ok" (process liveness), capabilities carry readiness.
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    # Injected fakes are ready by construction.
    assert body["capabilities"]["llm"]["ready"] is True
    assert body["capabilities"]["embed"]["ready"] is True


def test_health_reports_missing_embedding_config(tmp_path):
    """feat-047: a missing embedding config must be visible, not a silent timeout later."""
    from memoria.web.config import (
        EMBED_MISSING_HINT,
        CustomModel,
        CustomProvider,
        Settings,
        capability_status,
    )

    # What the acceptance run actually looked like: selectors empty, defaults filled in.
    settings = Settings(
        active_provider_id="p1",
        active_chat_model="m1",
        active_embed_provider_id="",
        active_embed_model="",
        embed_base_url="https://api.deepseek.com/v1",
        embed_api_key="",
        embed_model="text-embedding-3-small",  # the default, not a user choice
        providers=[
            CustomProvider(
                id="p1",
                name="p1",
                base_url="https://x.example/v1",
                models=[CustomModel(id="m1", model_type="chat")],
            )
        ],
    )
    caps = capability_status(settings)
    assert caps["llm"]["ready"] is True
    assert caps["embed"]["ready"] is False
    assert caps["embed"]["reason"] == EMBED_MISSING_HINT
    assert caps["embed"]["model"] == ""  # the default must not be reported as configured


def test_health_reports_ready_when_embedding_is_configured():
    from memoria.web.config import Settings, capability_status

    settings = Settings(
        active_provider_id="p1",
        active_chat_model="m1",
        active_embed_model="text-embedding-3-large",
        embed_api_key="sk-real",
        embed_model="text-embedding-3-large",
    )
    caps = capability_status(settings)
    assert caps["embed"]["ready"] is True
    assert caps["embed"]["model"] == "text-embedding-3-large"
    assert caps["embed"]["reason"] == ""


def test_health_reports_missing_chat_model():
    from memoria.web.config import LLM_MISSING_HINT, Settings, capability_status

    caps = capability_status(Settings())
    assert caps["llm"]["ready"] is False
    assert caps["llm"]["reason"] == LLM_MISSING_HINT


def test_pick_model_id_never_falls_back_across_types():
    """feat-058: an embedding model must never be auto-picked as chat (or vice versa)."""
    from memoria.web.config import CustomModel, CustomProvider, pick_model_id

    provider = CustomProvider(
        id="p1",
        name="p1",
        base_url="https://x.example/v1",
        models=[
            CustomModel(id="emb-1", model_type="embedding"),
            CustomModel(id="chat-1", model_type="chat", enabled=False),
        ],
    )
    assert pick_model_id(provider, "chat") == ""  # disabled chat skipped, no emb fallback
    assert pick_model_id(provider, "embedding") == "emb-1"
    assert pick_model_id(provider, "unknown-type") == ""


def test_resolve_active_chat_model_repairs_cross_typed_selector():
    """A live config was found with an embedding model as active_chat_model; the
    resolver must treat such a selector as unconfigured and self-heal instead of
    reporting the gateway ready with a model that cannot chat."""
    from memoria.web.config import (
        CustomModel,
        CustomProvider,
        Settings,
        capability_status,
        resolve_active_chat_model,
    )

    provider = CustomProvider(
        id="p1",
        name="p1",
        base_url="https://x.example/v1",
        models=[
            CustomModel(id="emb-1", model_type="embedding"),
            CustomModel(id="chat-1", model_type="chat"),
            CustomModel(id="chat-2", model_type="chat"),
        ],
    )

    # The corrupted shape seen in the wild: active_chat_model is an embedding id.
    corrupted = Settings(
        active_provider_id="p1",
        active_chat_model="emb-1",
        providers=[provider],
    )
    assert resolve_active_chat_model(corrupted) == "chat-1"
    assert capability_status(corrupted)["llm"]["ready"] is True

    # A genuine chat selector passes through untouched.
    healthy = Settings(active_provider_id="p1", active_chat_model="chat-2", providers=[provider])
    assert resolve_active_chat_model(healthy) == "chat-2"

    # A disabled active provider resolves to nothing (flat fields take over at runtime).
    provider.enabled = False
    disabled = Settings(active_provider_id="p1", active_chat_model="chat-2", providers=[provider])
    assert resolve_active_chat_model(disabled) == ""

    # No provider selected: the flat env-style path applies.
    assert resolve_active_chat_model(Settings()) == ""


# Dummy keys shaped like the setup placeholder. These are NOT real credentials;
# the point of the tests below is that they must not read as configured.
PLACEHOLDER_KEY = "-".join(["sk", "1234567890"])
FAKE_KEY = "sk-" + "not-a-real-credential"


def test_placeholder_api_key_does_not_count_as_configured():
    """feat-049: a leftover setup placeholder must not read as a working key.

    The acceptance run had a placeholder embed key with no embedding provider
    selected, which the first version of this check wrongly called "ready".
    """
    from memoria.web.config import EMBED_MISSING_HINT, Settings, capability_status

    settings = Settings(
        active_provider_id="p1",
        active_chat_model="m1",
        active_embed_provider_id="",
        active_embed_model="",
        embed_api_key=PLACEHOLDER_KEY,
        embed_model="text-embedding-3-small",
    )
    caps = capability_status(settings)
    assert caps["embed"]["ready"] is False
    assert caps["embed"]["reason"] == EMBED_MISSING_HINT

    # A non-placeholder key plus a model is accepted.
    ok = Settings(
        active_provider_id="p1",
        active_chat_model="m1",
        embed_api_key=FAKE_KEY,
        embed_model="text-embedding-3-small",
    )
    assert capability_status(ok)["embed"]["ready"] is True


def test_embedding_provider_with_placeholder_key_is_not_ready():
    from memoria.web.config import CustomProvider, Settings, capability_status

    settings = Settings(
        active_provider_id="p1",
        active_chat_model="m1",
        active_embed_provider_id="p1",
        active_embed_model="emb-1",
        providers=[
            CustomProvider(
                id="p1", name="p1", base_url="https://x.example/v1", api_key=PLACEHOLDER_KEY
            )
        ],
    )
    assert capability_status(settings)["embed"]["ready"] is False


def test_missing_embedding_config_returns_actionable_502(tmp_path, monkeypatch):
    """feat-048: ask/ingest must say what to fix instead of leaking a socket timeout.

    Drives the real guard with the acceptance run's settings: chat configured,
    embedding selector empty, no injected embedder.
    """
    from memoria.web import app as app_mod
    from memoria.web.config import EMBED_MISSING_HINT, CustomProvider, Settings

    unconfigured = Settings(
        active_provider_id="p1",
        active_chat_model="m1",
        active_embed_model="",
        providers=[CustomProvider(id="p1", name="p1", base_url="https://x.example/v1")],
    )
    # app.py imported load_settings by name, so patch the reference it uses.
    monkeypatch.setattr(app_mod, "load_settings", lambda *a, **kw: unconfigured)

    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    app = create_app(
        {
            "store": ChromaStore(path=str(tmp_path / "chroma")),
            "wiki": wiki,
            "checkpointer": MemorySaver(),
        }
    )
    client = TestClient(app)

    health = client.get("/api/health").json()
    assert health["capabilities"]["embed"]["ready"] is False

    ask = client.post("/api/ask", json={"question": "hi"})
    assert ask.status_code == 502
    assert ask.json()["detail"] == EMBED_MISSING_HINT
    assert "向量模型" in ask.json()["detail"]

    ing = client.post("/api/ingest", json={"text": "x", "origin": "n.txt"})
    assert ing.status_code == 502
    assert ing.json()["detail"] == EMBED_MISSING_HINT


def test_configured_embedding_is_not_blocked(tmp_path, monkeypatch):
    """feat-048: the guard only fires on a genuinely missing config."""
    from memoria.web import app as app_mod
    from memoria.web.config import CustomProvider, Settings

    ready = Settings(
        active_provider_id="p1",
        active_chat_model="m1",
        active_embed_model="text-embedding-3-large",
        embed_api_key=FAKE_KEY,
        providers=[CustomProvider(id="p1", name="p1", base_url="https://x.example/v1")],
    )
    monkeypatch.setattr(app_mod, "load_settings", lambda *a, **kw: ready)

    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    app = create_app(
        {
            "store": ChromaStore(path=str(tmp_path / "chroma")),
            "wiki": wiki,
            "checkpointer": MemorySaver(),
            "llm": SmartChat(),
        }
    )
    client = TestClient(app)
    assert client.get("/api/health").json()["capabilities"]["embed"]["ready"] is True
    # Not blocked by the guard — it proceeds to the real call path.
    resp = client.post("/api/ask", json={"question": "hi"})
    assert "未配置向量模型" not in resp.text


def test_injected_embedder_is_never_blocked(tmp_path):
    """feat-048: tests and demo mode inject fakes; the guard must stand aside."""
    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    app = create_app(
        {
            "store": ChromaStore(path=str(tmp_path / "chroma")),
            "embedder": FakeEmbedder(),
            "llm": SmartChat(),
            "wiki": wiki,
            "checkpointer": MemorySaver(),
        }
    )
    client = TestClient(app)
    assert client.get("/api/health").json()["capabilities"]["embed"]["ready"] is True


def test_default_checkpointer_is_sqlite(tmp_path):
    """feat-033: without an override the graph persists on disk via SqliteSaver."""
    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    app = create_app({
        "store": ChromaStore(path=str(tmp_path / "chroma")),
        "embedder": FakeEmbedder(),
        "llm": SmartChat(),
        "wiki": wiki,
        "checkpoint_db": str(tmp_path / "cp.sqlite"),
    })
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    assert (tmp_path / "cp.sqlite").exists()  # graph state lands on disk, not memory


def test_ask_conversation_memory(tmp_path):
    """feat-034: same conversation_id replays prior turns into the follow-up prompts."""
    llm = SmartChat()
    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    app = create_app({
        "store": ChromaStore(path=str(tmp_path / "chroma")),
        "embedder": FakeEmbedder(),
        "llm": llm,
        "wiki": wiki,
        "checkpointer": MemorySaver(),
    })
    client = TestClient(app)

    first = client.post(
        "/api/ask", json={"question": "服务 A 何时到期？", "conversation_id": "conv-1"}
    ).json()
    assert first["conversation_id"] == "conv-1"

    n_first = len(llm.calls)
    follow = client.post(
        "/api/ask", json={"question": "那要提前多久？", "conversation_id": "conv-1"}
    ).json()
    assert follow["conversation_id"] == "conv-1"
    recent = "\n".join(u for _, u in llm.calls[n_first:])
    assert "服务 A 何时到期" in recent  # prior turn reached the model

    # A fresh conversation id starts with a clean memory.
    n_fresh = len(llm.calls)
    client.post("/api/ask", json={"question": "换个话题", "conversation_id": "conv-2"})
    fresh = "\n".join(u for _, u in llm.calls[n_fresh:])
    assert "服务 A 何时到期" not in fresh

    # Omitting conversation_id mints a new thread instead of failing.
    auto = client.post("/api/ask", json={"question": "服务 A 何时到期？"}).json()
    assert auto["conversation_id"] not in {"", "conv-1", "conv-2"}


def test_agent_endpoint_runs_the_router(tmp_path):
    """feat-045: /api/agent omits `intent`, so the graph's conditional edges route it.

    This is the production path that keeps the router honest — the structured
    endpoints preset `intent` and therefore never exercise it.
    """
    llm = SmartChat()
    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    app = create_app({
        "store": ChromaStore(path=str(tmp_path / "chroma")),
        "embedder": FakeEmbedder(),
        "llm": llm,
        "wiki": wiki,
        "checkpointer": MemorySaver(),
    })
    client = TestClient(app)

    resp = client.post("/api/agent", json={"text": "服务 A 何时到期？"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "问答"
    assert body["conversation_id"]
    assert "2027" in body["text"]
    assert any("意图路由" in system for system, _ in llm.calls)

    # The qa branch shape is returned, same as /api/ask.
    assert "citations" in body and "source" in body


def test_agent_endpoint_can_preset_intent_to_skip_the_router(tmp_path):
    """An explicit intent short-circuits the router, matching the structured endpoints."""
    llm = SmartChat()
    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    app = create_app({
        "store": ChromaStore(path=str(tmp_path / "chroma")),
        "embedder": FakeEmbedder(),
        "llm": llm,
        "wiki": wiki,
        "checkpointer": MemorySaver(),
    })
    client = TestClient(app)
    body = client.post(
        "/api/agent", json={"text": "何时到期", "intent": "问答"}
    ).json()
    assert body["intent"] == "问答"
    assert not any("意图路由" in system for system, _ in llm.calls)


def test_agent_endpoint_ingest_branch(tmp_path):
    """feat-045: a non-question route returns the ingest shape, not the qa shape."""
    llm = SmartChat()
    llm.chat = lambda system, user: (
        llm.calls.append((system, user))
        or ("ingest" if "意图路由" in system else "## [[服务到期]]\n# 服务到期\n\n到期。\n")
    )
    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    raw = wiki.raw_dir / "note.txt"
    raw.write_text("服务 A 2027 到期。", encoding="utf-8")
    app = create_app({
        "store": ChromaStore(path=str(tmp_path / "chroma")),
        "embedder": FakeEmbedder(),
        "llm": llm,
        "wiki": wiki,
        "checkpointer": MemorySaver(),
    })
    client = TestClient(app)
    # The router only sees `text`; the ingest node needs a source_path, so this
    # documents the real contract: free text alone cannot fabricate a file ingest.
    body = client.post("/api/agent", json={"text": "把这个文件摄入"}).json()
    assert body["intent"] == "ingest"
    assert "chunks" in body
    assert "text" not in body


def test_structured_endpoints_still_skip_the_router(api_client):
    """The preset-intent optimisation must survive the /api/agent addition."""
    client, _, _ = api_client
    assert client.post("/api/ask", json={"question": "何时到期"}).status_code == 200


def test_frontend_static_serving(api_client):
    client, _, _ = api_client
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Memoria" in resp.text
    assert "<div id=\"root\">" in resp.text


def test_load_settings_filters_non_public_urls(tmp_path, monkeypatch):
    from memoria.web.config import load_settings

    monkeypatch.setenv("MEMORIA_LLM_BASE_URL", "https://env-llm.example/v1")
    monkeypatch.setenv("MEMORIA_EMBED_BASE_URL", "https://env-embed.example/v1")
    path = tmp_path / "settings.json"
    path.write_text(
        '{"llm_base_url":"http://127.0.0.1/v1",'
        '"embed_base_url":"http://10.0.0.1/v1"}',
        encoding="utf-8",
    )

    settings = load_settings(path)

    assert settings.llm_base_url == "https://env-llm.example/v1"
    assert settings.embed_base_url == "https://env-embed.example/v1"


def test_config_api_rejects_non_public_https_urls(api_client):
    client, _, _ = api_client
    credential_marker = "x" * 12

    assert client.post("/api/config/models", json={"base_url": "http://localhost/v1", "api_key": credential_marker}).status_code == 400
    assert client.post("/api/config/models", json={"base_url": "https://gateway.example:8443/v1"}).status_code == 400
    assert client.post(
        "/api/config/test",
        json={
            "llm_base_url": "https://localhost/v1",
            "llm_api_key": credential_marker,
            "llm_model": "m",
            "embed_base_url": "",
            "embed_api_key": credential_marker,
            "embed_model": "e",
        },
    ).status_code == 400
    assert all(
        credential_marker not in response.text
        for response in [
            client.post("/api/config/models", json={"base_url": "http://localhost/v1", "api_key": credential_marker}),
        ]
    )


def test_fetch_models_falls_back_to_the_stored_key(api_client, monkeypatch):
    """feat-056: the settings UI only has a masked key, so an empty api_key must
    resolve to the provider's stored credential instead of sending no auth."""
    from memoria.web.config import CustomProvider, Settings

    stored_key = "sk-" + "stored-credential-not-real"
    current = Settings(
        providers=[
            CustomProvider(
                id="p1",
                name="p1",
                base_url="https://gateway.example/v1",
                api_key=stored_key,
            )
        ]
    )
    monkeypatch.setattr("memoria.web.config_routes.load_settings", lambda: current)

    seen = {}

    def fake_fetch(base_url, api_key, api_format):
        seen["api_key"] = api_key
        seen["base_url"] = base_url
        return ["model-a", "model-b"]

    monkeypatch.setattr("memoria.web.config_routes.fetch_remote_models", fake_fetch)

    client, _, _ = api_client
    resp = client.post(
        "/api/config/models",
        json={"base_url": "https://gateway.example/v1", "provider_id": "p1"},
    )
    assert resp.status_code == 200
    assert resp.json()["models"] == ["model-a", "model-b"]
    assert seen["api_key"] == stored_key, "must fall back to the stored credential"

    # An explicitly typed key still wins over the stored one.
    typed = "sk-" + "typed-key-not-real"
    client.post(
        "/api/config/models",
        json={
            "base_url": "https://gateway.example/v1",
            "api_key": typed,
            "provider_id": "p1",
        },
    )
    assert seen["api_key"] == typed


def test_fetch_models_error_carries_the_reason(api_client, monkeypatch):
    """A bare "获取模型失败" told the user nothing; surface the real cause."""
    monkeypatch.setattr(
        "memoria.web.config_routes.fetch_remote_models",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("HTTP 401")),
    )
    client, _, _ = api_client
    resp = client.post("/api/config/models", json={"base_url": "https://gateway.example/v1"})
    assert resp.status_code == 400
    message = resp.json()["message"]
    assert "401" in message, f"the status code must reach the user: {message!r}"
    assert resp.json()["models"] == []


def test_cors_allows_only_local_development_origins(api_client):
    client, _, _ = api_client

    for origin in ("http://localhost:3000", "http://127.0.0.1:3000"):
        response = client.get("/api/health", headers={"Origin": origin})
        assert response.headers["access-control-allow-origin"] == origin

    blocked = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in blocked.headers


def test_fetch_models_endpoint(api_client, monkeypatch):
    client, _, _ = api_client

    class MockResp:
        status = 200
        def raise_for_status(self): pass
        def json(self):
            return {"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]}

    monkeypatch.setattr("memoria.web.config.safe_request", lambda *a, **kw: MockResp())
    resp = client.post("/api/config/models", json={"base_url": "https://api.deepseek.com/v1", "api_key": "x" * 12})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "deepseek-chat" in data["models"]


def test_test_config_endpoint(api_client, monkeypatch):
    client, _, _ = api_client

    class MockResp:
        status = 200
        text = "ok"
        def json(self):
            return {"choices": [{"message": {"content": "pong"}}]}

    monkeypatch.setattr("memoria.web.config.safe_request", lambda *a, **kw: MockResp())
    resp = client.post(
        "/api/config/test",
        json={
            "llm_base_url": "https://api.deepseek.com/v1",
            "llm_api_key": "x" * 12,
            "llm_model": "deepseek-chat",
            "embed_base_url": "",
            "embed_api_key": "",
            "embed_model": "",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["llm_ok"] is True


def test_provider_crud_and_model_management(api_client, monkeypatch):
    from memoria.web.config import Settings

    client, _, _ = api_client
    current = Settings()

    def load_current():
        return current.model_copy(deep=True)

    def save_current(settings):
        nonlocal current
        current = settings.model_copy(deep=True)

    monkeypatch.setattr("memoria.web.config_routes.load_settings", load_current)
    monkeypatch.setattr("memoria.web.config_routes.save_settings", save_current)

    secret_key = "x" * 24
    # 1. Create provider
    create_resp = client.post(
        "/api/config/providers",
        json={
            "name": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_format": "chat_completions",
            "api_key": secret_key,
            "enabled": True,
        },
    )
    assert create_resp.status_code == 200
    pdata = create_resp.json()["provider"]
    provider_id = pdata["id"]
    assert provider_id == "openrouter"
    assert pdata["api_key_set"] is True
    assert pdata["masked_api_key"] == "xxxx...xxxx"
    assert secret_key not in create_resp.text
    assert current.active_provider_id == "openrouter"

    # 2. Get providers
    list_resp = client.get("/api/config/providers")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["providers"]) == 1
    assert list_resp.json()["active_provider_id"] == "openrouter"

    # 3. Add models (including slash in model ID)
    m1_resp = client.post(
        f"/api/config/providers/{provider_id}/models",
        json={
            "id": "stealth/union-alpha",
            "name": "stealth/union-alpha",
            "tags": ["1M"],
            "enabled": True,
            "model_type": "chat",
        },
    )
    assert m1_resp.status_code == 200
    assert m1_resp.json()["model"]["id"] == "stealth/union-alpha"
    assert m1_resp.json()["model"]["tags"] == ["1M"]
    assert current.active_chat_model == "stealth/union-alpha"

    m2_resp = client.post(
        f"/api/config/providers/{provider_id}/models",
        json={
            "id": "stealth/space-bunny",
            "name": "Space Bunny",
            "tags": ["1M", "视觉"],
            "enabled": True,
            "model_type": "chat",
        },
    )
    assert m2_resp.status_code == 200
    assert len(m2_resp.json()["provider"]["models"]) == 2

    # 4. Test provider connectivity
    monkeypatch.setattr(
        "memoria.web.config_routes.test_model_connectivity",
        lambda req: {"llm_ok": True, "llm_latency_ms": 120, "llm_message": "连接成功 (120ms)"},
    )
    test_resp = client.post(f"/api/config/providers/{provider_id}/test", json={"model_id": "stealth/space-bunny"})
    assert test_resp.status_code == 200
    assert test_resp.json()["llm_ok"] is True

    # 5. Activate second model
    act_resp = client.post(
        "/api/config/providers/activate",
        json={"provider_id": provider_id, "model_id": "stealth/space-bunny"},
    )
    assert act_resp.status_code == 200
    assert act_resp.json()["active_chat_model"] == "stealth/space-bunny"
    assert current.llm_model == "stealth/space-bunny"
    assert current.llm_base_url == "https://openrouter.ai/api/v1"

    # 6. Delete model with slash
    del_m_resp = client.delete(f"/api/config/providers/{provider_id}/models/stealth/union-alpha")
    assert del_m_resp.status_code == 200
    remaining_models = del_m_resp.json()["provider"]["models"]
    assert len(remaining_models) == 1
    assert remaining_models[0]["id"] == "stealth/space-bunny"

    # 7. Delete provider
    del_p_resp = client.delete(f"/api/config/providers/{provider_id}")
    assert del_p_resp.status_code == 200
    assert del_p_resp.json()["providers"] == []
    assert current.active_provider_id == ""


def test_provider_protocol_persists_and_rejects_unknown_formats(api_client, monkeypatch):
    from memoria.web.config import Settings

    client, _, _ = api_client
    current = Settings()
    secret = "s" * 16

    def load_current():
        return current.model_copy(deep=True)

    def save_current(settings):
        nonlocal current
        current = settings.model_copy(deep=True)

    monkeypatch.setattr("memoria.web.config_routes.load_settings", load_current)
    monkeypatch.setattr("memoria.web.config_routes.save_settings", save_current)

    create = client.post(
        "/api/config/providers",
        json={
            "name": "Claude Gateway",
            "base_url": "https://gateway.example/v1",
            "api_format": "anthropic_messages",
            "api_key": secret,
        },
    )
    assert create.status_code == 200
    provider_id = create.json()["provider"]["id"]
    assert create.json()["provider"]["api_format"] == "anthropic_messages"

    update = client.post(
        "/api/config/providers",
        json={
            "id": provider_id,
            "name": "Claude Gateway",
            "base_url": "https://gateway.example/v1",
            "api_format": "openai_responses",
            "api_key": "",
        },
    )
    assert update.status_code == 200
    assert update.json()["provider"]["api_format"] == "openai_responses"
    assert client.get("/api/config/providers").json()["providers"][0]["api_format"] == "openai_responses"

    unknown = client.post(
        "/api/config/providers",
        json={
            "name": "Unknown",
            "base_url": "https://gateway.example/v1",
            "api_format": "gemini",
        },
    )
    assert unknown.status_code == 400


def test_embedding_provider_is_independent_from_chat_provider(api_client, monkeypatch):
    from memoria.web.config import CustomModel, CustomProvider, Settings

    client, _, _ = api_client
    chat_key = "c" * 12
    embed_key = "e" * 12
    chat_provider = CustomProvider(
        id="chat-provider",
        name="Chat Provider",
        base_url="https://chat.example/v1",
        api_format="chat_completions",
        api_key=chat_key,
        enabled=True,
        models=[CustomModel(id="chat-model", name="Chat Model", model_type="chat")],
    )
    embed_provider = CustomProvider(
        id="embed-provider",
        name="Embed Provider",
        base_url="https://embed.example/v1",
        api_format="chat_completions",
        api_key=embed_key,
        enabled=True,
        models=[CustomModel(id="embed-model", name="Embed Model", model_type="embedding")],
    )
    current = Settings(
        active_provider_id="chat-provider",
        active_chat_model="chat-model",
        providers=[chat_provider, embed_provider],
        llm_base_url="https://chat.example/v1",
        llm_api_key=chat_key,
        llm_model="chat-model",
    )

    def load_current():
        return current.model_copy(deep=True)

    def save_current(settings):
        nonlocal current
        current = settings.model_copy(deep=True)

    monkeypatch.setattr("memoria.web.config_routes.load_settings", load_current)
    monkeypatch.setattr("memoria.web.config_routes.save_settings", save_current)

    activated = client.post(
        "/api/config/providers/activate",
        json={
            "provider_id": "embed-provider",
            "model_id": "embed-model",
            "model_type": "embedding",
        },
    )
    assert activated.status_code == 200
    assert activated.json()["active_embed_provider_id"] == "embed-provider"
    assert activated.json()["active_embed_model"] == "embed-model"
    assert current.active_provider_id == "chat-provider"
    assert current.active_chat_model == "chat-model"
    assert current.active_embed_provider_id == "embed-provider"
    assert current.active_embed_model == "embed-model"
    assert current.llm_base_url == "https://chat.example/v1"
    assert current.llm_api_key == chat_key
    assert current.llm_model == "chat-model"

    listed = client.get("/api/config/providers").json()
    assert listed["active_embed_provider_id"] == "embed-provider"

    saved_embed = client.post(
        "/api/config/providers",
        json={
            "id": "embed-provider",
            "name": "Embed Provider Renamed",
            "base_url": "https://embed.example/v1",
            "api_key": "",
            "enabled": True,
            "scope": "embedding",
        },
    )
    assert saved_embed.status_code == 200
    assert saved_embed.json()["provider"]["name"] == "Embed Provider Renamed"
    assert current.active_provider_id == "chat-provider"
    assert current.active_chat_model == "chat-model"
    assert current.llm_base_url == "https://chat.example/v1"

    deleted = client.delete("/api/config/providers/embed-provider")
    assert deleted.status_code == 200
    assert current.active_provider_id == "chat-provider"
    assert current.active_chat_model == "chat-model"
    assert current.active_embed_provider_id == ""
    assert current.active_embed_model == ""


def test_legacy_settings_load_with_default_embed_provider_state(tmp_path):
    from memoria.web.config import load_settings

    path = tmp_path / "settings.json"
    path.write_text('{"llm_model": "legacy-model"}', encoding="utf-8")

    settings = load_settings(path)

    assert settings.llm_model == "legacy-model"
    assert settings.active_embed_provider_id == ""


def test_provider_protocol_controls_model_list_and_connectivity(api_client, monkeypatch):
    client, _, _ = api_client
    secret = "t" * 16
    calls = []

    class MockResponse:
        status = 200
        text = "ok"

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": "claude-model"}]}

    def fake_request(url, method, headers, json_body=None, timeout=10.0, max_bytes=1024 * 1024):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        return MockResponse()

    monkeypatch.setattr("memoria.web.config.safe_request", fake_request)
    models = client.post(
        "/api/config/models",
        json={
            "base_url": "https://gateway.example/v1",
            "api_key": secret,
            "api_format": "anthropic_messages",
        },
    )
    assert models.status_code == 200
    assert models.json()["models"] == ["claude-model"]
    assert calls[0]["url"] == "https://gateway.example/v1/models"
    assert calls[0]["headers"]["x-api-key"] == secret
    assert calls[0]["headers"]["anthropic-version"] == "2023-06-01"

    calls.clear()
    tested = client.post(
        "/api/config/test",
        json={
            "llm_base_url": "https://gateway.example/v1",
            "llm_api_key": secret,
            "llm_model": "claude-model",
            "api_format": "anthropic_messages",
            "embed_base_url": "",
            "embed_model": "",
        },
    )
    assert tested.status_code == 200
    assert calls[0]["url"] == "https://gateway.example/v1/messages"
    assert "system" not in calls[0]["json_body"]
    assert calls[0]["json_body"]["max_tokens"] == 5


def test_provider_rejects_invalid_urls_and_errors(api_client):
    client, _, _ = api_client

    # Invalid URL
    bad_url_resp = client.post(
        "/api/config/providers",
        json={"name": "local", "base_url": "http://127.0.0.1:8000/v1"},
    )
    assert bad_url_resp.status_code == 400

    # Empty name
    bad_name_resp = client.post(
        "/api/config/providers",
        json={"name": "   ", "base_url": "https://api.example.com/v1"},
    )
    assert bad_name_resp.status_code == 400

    # Non-existent provider
    assert client.delete("/api/config/providers/missing").status_code == 404
    assert client.post("/api/config/providers/missing/models", json={"id": "m1"}).status_code == 404
    assert client.post("/api/config/providers/missing/test").status_code == 404
    assert client.post("/api/config/providers/activate", json={"provider_id": "missing"}).status_code == 404


def _ingest_raw(client, wiki, name, body):
    """Upload + dual-ingest a raw file through the public API; returns doc_id."""
    resp = client.post(
        "/api/ingest",
        json={"text": body, "origin": name},
    )
    assert resp.status_code == 200
    return resp.json()["doc_id"]


def test_documents_list_and_delete_no_orphan_vectors(api_client, tmp_path):
    client, wiki, store = api_client
    doc_id = _ingest_raw(client, wiki, "note-a.md", "服务 A 将于 2027-01-01 到期。" * 10)
    assert store.count() > 0
    assert doc_id in store.documents()  # chunked into several vectors

    listing = client.get("/api/documents").json()
    entry = next(d for d in listing["documents"] if d["doc_id"] == doc_id)
    assert entry["name"] == "note-a.md" and entry["chunks"] > 0

    resp = client.delete(f"/api/documents/{doc_id}")
    assert resp.status_code == 200
    assert resp.json()["raw_removed"] == "note-a.md"

    # Red line: not a single vector of the deleted doc may remain.
    assert store.count() == 0 and doc_id not in store.documents()
    assert not (wiki.raw_dir / "note-a.md").exists()
    assert "删除文档" in (wiki.read_page("log") or "")

    after = client.get("/api/documents").json()
    assert all(d["doc_id"] != doc_id for d in after["documents"])


def test_delete_document_without_raw_file_still_purges_vectors(api_client):
    client, wiki, store = api_client
    doc_id = _ingest_raw(client, wiki, "note-b.md", "内容内容内容。" * 10)
    (wiki.raw_dir / "note-b.md").unlink()  # raw already gone, vectors remain

    resp = client.delete(f"/api/documents/{doc_id}")
    assert resp.status_code == 200
    assert resp.json()["raw_removed"] is None
    assert store.count() == 0
    vector_only = client.get("/api/documents").json()["vector_only"]
    assert all(d["doc_id"] != doc_id for d in vector_only)


def test_delete_unknown_document_404(api_client):
    client, _, _ = api_client
    resp = client.delete("/api/documents/deadbeefdeadbeef")
    assert resp.status_code == 404


def test_ask_endpoint(api_client):
    client, wiki, _ = api_client
    wiki.write_page("服务到期", "# 服务到期\n\n2027 到期。\n")
    wiki.build_index()

    resp = client.post("/api/ask", json={"question": "服务到期时间？"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "wiki"
    assert "2027" in data["text"]
    assert "服务到期" in data["wiki_pages"]
    assert data["citations_verified"] is True


def test_wiki_pages_and_detail(api_client):
    client, wiki, _ = api_client
    wiki.write_page("页面A", "# 页面A\n\n参考 [[页面B]]。\n")
    wiki.write_page("页面B", "# 页面B\n\n内容B。\n")
    wiki.build_index()

    resp = client.get("/api/wiki/pages")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["pages"]) >= 2
    assert "lint" in data

    page_resp = client.get("/api/wiki/page/页面B")
    assert page_resp.status_code == 200
    page_data = page_resp.json()
    assert page_data["name"] == "页面B"
    assert "页面A" in page_data["backlinks"]


def test_archive_qa_endpoint(api_client):
    client, wiki, _ = api_client
    resp = client.post(
        "/api/wiki/archive-qa",
        json={
            "question": "什么是 Memoria？",
            "answer": "Memoria 是个人知识系统。",
            "citations": [{"ref": 1, "doc_id": "doc1", "chunk": 0, "start": 0}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "问答归档" in data["name"]
    assert wiki.read_page(data["name"]) is not None


def test_mail_triage_and_archive_red_line(api_client):
    client, _, _ = api_client
    resp = client.get("/api/mail/triage")
    assert resp.status_code == 200
    data = resp.json()
    thread_id = data["thread_id"]
    assert thread_id
    items = data["triages"]
    assert len(items) == 2

    # m1 is OTP verification -> must be protected
    otp_item = next(i for i in items if i["id"] == "m1")
    assert otp_item["protected"] is True
    assert otp_item["can_archive"] is False

    # m2 is marketing -> candidate
    mkt_item = next(i for i in items if i["id"] == "m2")
    assert mkt_item["protected"] is False
    assert mkt_item["can_archive"] is True
    assert data["pending"] == ["m2"]  # graph interrupt carries exactly this whitelist

    # Attempt to archive m1 (protected) + m2 (marketing)
    arch_resp = client.post(
        "/api/mail/archive",
        json={"confirmed_ids": ["m1", "m2"], "thread_id": thread_id},
    )
    assert arch_resp.status_code == 200
    arch_data = arch_resp.json()
    # Red line: m1 must be blocked from archiving!
    assert "m1" in arch_data["blocked"]
    assert "m2" in arch_data["archived"]

    # The triage thread is finished: another archive round-trip is a no-op.
    again = client.post(
        "/api/mail/archive",
        json={"confirmed_ids": ["m2"], "thread_id": thread_id},
    )
    assert again.status_code == 200
    assert again.json()["archived"] == []

    # Confirmed candidates are single-use.
    replay = client.post(
        "/api/mail/archive",
        json={"confirmed_ids": ["m2"], "thread_id": thread_id},
    ).json()
    assert replay["archived"] == []
    assert "m2" in replay["blocked"]


def test_wiki_deep_lint_flags_contradictions(api_client, tmp_path):
    """feat-036: deep=true runs the LLM contradiction check; default stays free."""
    client, wiki, _ = api_client
    wiki.write_page("A", "# A\n\n见 [[B]]。\n")
    wiki.write_page("B", "# B\n\n回链 [[A]]。\n")
    wiki.build_index()

    plain = client.get("/api/wiki/pages").json()
    assert plain["lint"]["contradictions"] == []

    # A dedicated app whose LLM always says YES surfaces the contradiction.
    from memoria.llm import FakeChat

    yes_app = create_app({
        "store": ChromaStore(path=str(tmp_path / "chroma")),
        "embedder": FakeEmbedder(),
        "llm": FakeChat("YES: A 说免费，B 说收费"),
        "wiki": wiki,
        "checkpointer": MemorySaver(),
    })
    deep = TestClient(yes_app).get("/api/wiki/pages?deep=true").json()
    assert len(deep["lint"]["contradictions"]) == 1
    assert "[[A]] vs [[B]]" in deep["lint"]["contradictions"][0]


def test_mail_fact_writes_back_to_wiki(api_client):
    """feat-037: email-derived facts compound into wiki pages, deduped."""
    client, wiki, _ = api_client
    resp = client.post(
        "/api/mail/fact",
        json={"msg_id": "m9", "page": "服务到期", "fact": "服务 A 到期日 2027-01-01"},
    )
    assert resp.status_code == 200
    assert resp.json()["added"] is True
    body = wiki.read_page("服务到期") or ""
    assert "2027-01-01" in body and "mail:m9" in body

    dup = client.post(
        "/api/mail/fact",
        json={"msg_id": "m9", "page": "服务到期", "fact": "服务 A 到期日 2027-01-01"},
    ).json()
    assert dup["added"] is False

    bad = client.post(
        "/api/mail/fact",
        json={"msg_id": "m9", "page": "../escape", "fact": "x"},
    )
    assert bad.status_code == 400


def test_mail_archive_rejects_ids_without_fresh_triage(api_client):
    client, _, _ = api_client

    missing_thread = client.post("/api/mail/archive", json={"confirmed_ids": ["m2"]})
    assert missing_thread.status_code == 400  # no triage session -> no archive at all

    without_triage = client.post(
        "/api/mail/archive", json={"confirmed_ids": ["m2"], "thread_id": "ghost-thread"}
    )
    assert without_triage.status_code == 200
    assert without_triage.json()["archived"] == []
    assert "m2" in without_triage.json()["blocked"]

    triage = client.get("/api/mail/triage").json()
    unknown = client.post(
        "/api/mail/archive",
        json={"confirmed_ids": ["unknown"], "thread_id": triage["thread_id"]},
    )
    assert unknown.status_code == 200
    assert unknown.json()["archived"] == []
    assert "unknown" in unknown.json()["blocked"]


def test_ingest_text_endpoint(api_client):
    client, wiki, store = api_client
    resp = client.post(
        "/api/ingest",
        json={
            "text": "测试文档内容：Memoria 包含 RAG 与 Wiki 双写。",
            "origin": "test_doc.md",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["chunks"] > 0
    assert store.count() > 0
    assert len(data["wiki_pages"]) > 0


@pytest.mark.parametrize(
    "unsafe_name",
    ["../escape.md", "sub/../escape.md", "..\\escape.md", "/tmp/escape.md", "C:\\escape.md"],
)
def test_ingest_rejects_unsafe_text_origins(api_client, unsafe_name):
    client, wiki, _ = api_client

    response = client.post(
        "/api/ingest",
        json={"text": "unsafe", "origin": unsafe_name},
    )

    assert response.status_code == 400
    assert not (wiki.root.parent / "escape.md").exists()
    assert not (wiki.raw_dir / "escape.md").exists()


@pytest.mark.parametrize(
    "unsafe_name",
    ["../escape.md", "sub/../escape.md", "..\\escape.md", "/tmp/escape.md"],
)
def test_ingest_rejects_unsafe_upload_filenames(api_client, unsafe_name):
    client, wiki, _ = api_client

    response = client.post(
        "/api/ingest/file",
        files={"file": (unsafe_name, b"unsafe", "text/markdown")},
    )

    assert response.status_code == 400
    assert not (wiki.root.parent / "escape.md").exists()
    assert not (wiki.raw_dir / "escape.md").exists()


def test_ingest_accepts_safe_upload_filename(api_client):
    client, wiki, _ = api_client

    response = client.post(
        "/api/ingest/file",
        files={"file": ("safe.md", "安全文件内容".encode(), "text/markdown")},
    )

    assert response.status_code == 200
    assert response.json()["filename"] == "safe.md"
    assert (wiki.raw_dir / "safe.md").exists()

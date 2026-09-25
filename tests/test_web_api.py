"""Tests for feat-010/feat-033: Web API service (FastAPI), fully graph-backed. 100% offline."""

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
        if "Wiki 维护者" in system or "更新相关页面" in user:
            return "## [[服务到期]]\n# 服务到期\n\n2027 到期。\n"
        if "Wiki 检索器" in system:
            return "[[服务到期]]"
        if "回答质检员" in system:
            return "充分"
        if "邮件分类助手" in system:
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
    assert resp.json() == {"status": "ok", "version": "0.1.0"}


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


def test_frontend_static_serving(api_client):
    client, _, _ = api_client
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Memoria" in resp.text
    assert "<div id=\"root\">" in resp.text


def test_load_settings_supports_legacy_files_without_presets(tmp_path):
    from memoria.web.config import load_settings

    path = tmp_path / "settings.json"
    path.write_text('{"llm_model": "legacy-model"}', encoding="utf-8")

    settings = load_settings(path)

    assert settings.llm_model == "legacy-model"
    assert settings.presets == []


def test_load_settings_filters_non_public_urls_and_presets(tmp_path, monkeypatch):
    from memoria.web.config import load_settings

    monkeypatch.setenv("MEMORIA_LLM_BASE_URL", "https://env-llm.example/v1")
    monkeypatch.setenv("MEMORIA_EMBED_BASE_URL", "https://env-embed.example/v1")
    path = tmp_path / "settings.json"
    path.write_text(
        '{"llm_base_url":"http://127.0.0.1/v1",'
        '"embed_base_url":"http://10.0.0.1/v1","presets":['
        '{"name":"legacy","llm_base_url":"http://localhost/v1","llm_api_key":"k",'
        '"llm_model":"m","embed_base_url":"","embed_api_key":"","embed_model":"e"},'
        '{"name":"public","llm_base_url":"https://saved.example/v1","llm_api_key":"k",'
        '"llm_model":"m","embed_base_url":"https://saved.example/v1",'
        '"embed_api_key":"","embed_model":"e"}]}',
        encoding="utf-8",
    )

    settings = load_settings(path)

    assert settings.llm_base_url == "https://env-llm.example/v1"
    assert settings.embed_base_url == "https://env-embed.example/v1"
    assert [preset.name for preset in settings.presets] == ["public"]


def test_config_api_rejects_non_public_https_urls(api_client, monkeypatch):
    from memoria.web.config import ModelPreset, Settings

    client, _, _ = api_client
    credential_marker = "x" * 12
    current = Settings(
        presets=[
            ModelPreset(
                name="bad",
                llm_base_url="http://localhost/v1",
                llm_api_key="",
                llm_model="m",
                embed_base_url="",
                embed_api_key="",
                embed_model="e",
            )
        ]
    )
    monkeypatch.setattr("memoria.web.config_routes.load_settings", lambda: current)
    monkeypatch.setattr("memoria.web.config_routes.save_settings", lambda settings: None)
    invalid = {
        "llm_base_url": "http://localhost/v1",
        "llm_api_key": credential_marker,
        "llm_model": "m",
        "embed_base_url": "",
        "embed_api_key": credential_marker,
        "embed_model": "e",
    }

    assert client.post("/api/config", json=invalid).status_code == 400
    assert client.post("/api/config/presets", json={**invalid, "name": "bad-http"}).status_code == 400
    assert client.post("/api/config/models", json={"base_url": "http://localhost/v1", "api_key": credential_marker}).status_code == 400
    assert client.post("/api/config/models", json={"base_url": "https://gateway.example:8443/v1"}).status_code == 400
    assert client.post("/api/config/test", json={**invalid, "llm_base_url": "https://localhost/v1"}).status_code == 400
    assert client.post("/api/config/presets/bad/apply").status_code == 400
    assert all(credential_marker not in response.text for response in [
        client.post("/api/config", json=invalid),
        client.post("/api/config/presets", json={**invalid, "name": "bad-http"}),
    ])


def test_config_endpoints_redact_keys_and_preserve_empty_updates(api_client, monkeypatch):
    from memoria.web.config import Settings

    client, _, _ = api_client
    llm_secret = "x" * 12
    embed_secret = "y" * 12
    replacement_secret = "z" * 12
    current = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_api_key=llm_secret,
        llm_model="gpt-4o-mini",
        embed_base_url="https://api.openai.com/v1",
        embed_api_key=embed_secret,
        embed_model="text-embedding-3-small",
    )
    saved = []
    monkeypatch.setattr("memoria.web.config_routes.load_settings", lambda: current)
    monkeypatch.setattr("memoria.web.config_routes.save_settings", saved.append)

    get_resp = client.get("/api/config")
    assert get_resp.status_code == 200
    cfg = get_resp.json()
    assert "llm_base_url" in cfg
    assert "llm_api_key" not in cfg
    assert "embed_api_key" not in cfg
    assert cfg["llm_api_key_set"] is True
    assert cfg["embed_api_key_set"] is True
    assert llm_secret not in get_resp.text
    assert embed_secret not in get_resp.text

    post_resp = client.post(
        "/api/config",
        json={
            "llm_base_url": "https://api.deepseek.com/v1",
            "llm_api_key": "",
            "llm_model": "deepseek-chat",
            "embed_base_url": "https://api.deepseek.com/v1",
            "embed_api_key": "  ",
            "embed_model": "text-embedding-3-small",
            "demo_mode": False,
        },
    )
    assert post_resp.status_code == 200
    assert post_resp.json()["status"] == "ok"
    assert saved[-1].llm_api_key == llm_secret
    assert saved[-1].embed_api_key == embed_secret
    assert saved[-1].llm_model == "deepseek-chat"

    client.post(
        "/api/config",
        json={
            "llm_base_url": "https://api.deepseek.com/v1",
            "llm_api_key": replacement_secret,
            "llm_model": "deepseek-chat",
            "embed_base_url": "https://api.deepseek.com/v1",
            "embed_api_key": "",
            "embed_model": "text-embedding-3-small",
            "demo_mode": False,
        },
    )
    assert saved[-1].llm_api_key == replacement_secret
    assert saved[-1].embed_api_key == embed_secret


def test_config_presets_save_apply_and_delete_without_exposing_keys(api_client, monkeypatch):
    from memoria.web.config import Settings

    client, _, _ = api_client
    current_key = "a" * 12
    current_embed_key = "b" * 12
    preset_key = "c" * 12
    current = Settings(
        llm_base_url="https://current.example/v1",
        llm_api_key=current_key,
        llm_model="current-model",
        embed_base_url="https://current.example/v1",
        embed_api_key=current_embed_key,
        embed_model="current-embed-model",
    )

    def load_current():
        return current.model_copy(deep=True)

    def save_current(settings):
        nonlocal current
        current = settings.model_copy(deep=True)

    monkeypatch.setattr("memoria.web.config_routes.load_settings", load_current)
    monkeypatch.setattr("memoria.web.config_routes.save_settings", save_current)

    save_response = client.post(
        "/api/config/presets",
        json={
            "name": "  Work  ",
            "llm_base_url": "https://preset.example/v1",
            "llm_api_key": preset_key,
            "llm_model": "preset-model",
            "embed_base_url": "https://preset.example/v1",
            "embed_api_key": "",
            "embed_model": "preset-embed-model",
            "demo_mode": False,
        },
    )
    assert save_response.status_code == 200
    assert save_response.json()["preset"]["name"] == "Work"
    assert preset_key not in save_response.text
    assert current_embed_key not in save_response.text
    assert current.llm_model == "current-model"
    assert current.presets[0].llm_api_key == preset_key
    assert current.presets[0].embed_api_key == current_embed_key

    get_response = client.get("/api/config")
    assert get_response.status_code == 200
    assert get_response.json()["presets"][0]["name"] == "Work"
    assert preset_key not in get_response.text

    save_current_response = client.post(
        "/api/config",
        json={
            "llm_base_url": "https://saved.example/v1",
            "llm_api_key": "",
            "llm_model": "saved-current-model",
            "embed_base_url": "https://saved.example/v1",
            "embed_api_key": "",
            "embed_model": "saved-current-embed-model",
            "demo_mode": False,
        },
    )
    assert save_current_response.status_code == 200
    assert current.llm_model == "saved-current-model"
    assert current.llm_api_key == current_key
    assert len(current.presets) == 1

    apply_response = client.post("/api/config/presets/work/apply")
    assert apply_response.status_code == 200
    assert apply_response.json()["config"]["llm_model"] == "preset-model"
    assert preset_key not in apply_response.text
    assert current.llm_model == "preset-model"
    assert current.llm_api_key == preset_key
    assert len(current.presets) == 1

    delete_response = client.delete("/api/config/presets/WORK")
    assert delete_response.status_code == 200
    assert delete_response.json()["presets"] == []
    assert current.llm_model == "preset-model"
    assert current.presets == []

    assert client.post("/api/config/presets/missing/apply").status_code == 404
    assert client.delete("/api/config/presets/missing").status_code == 404


def test_config_preset_names_are_unique_and_limited_to_ten(api_client, monkeypatch):
    from memoria.web.config import Settings

    client, _, _ = api_client
    current = Settings(llm_api_key="d" * 12, embed_api_key="e" * 12)
    saved = []

    def load_current():
        return current.model_copy(deep=True)

    def save_current(settings):
        nonlocal current
        current = settings.model_copy(deep=True)
        saved.append(settings)

    monkeypatch.setattr("memoria.web.config_routes.load_settings", load_current)
    monkeypatch.setattr("memoria.web.config_routes.save_settings", save_current)

    def body(name):
        return {
            "name": name,
            "llm_base_url": "https://preset.example/v1",
            "llm_api_key": "",
            "llm_model": "preset-model",
            "embed_base_url": "https://preset.example/v1",
            "embed_api_key": "",
            "embed_model": "preset-embed-model",
            "demo_mode": False,
        }

    for invalid_name in ("", ".", "..", "../bad", "..\\bad"):
        assert client.post("/api/config/presets", json=body(invalid_name)).status_code == 400
    assert saved == []

    assert client.post("/api/config/presets", json=body("Work")).status_code == 200
    assert client.post("/api/config/presets", json=body("work")).status_code == 409
    assert len(saved) == 1

    for index in range(9):
        assert client.post("/api/config/presets", json=body(f"Preset {index}")).status_code == 200
    assert len(saved) == 10
    assert client.post("/api/config/presets", json=body("Overflow")).status_code == 409
    assert len(saved) == 10


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

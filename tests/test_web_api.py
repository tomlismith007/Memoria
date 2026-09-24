"""Tests for feat-010: Web API service (FastAPI). 100% offline."""

import pytest
from starlette.testclient import TestClient

from memoria.mail import Email
from memoria.rag import ChromaStore, FakeEmbedder, ingest_document
from memoria.web.app import create_app
from memoria.wiki import Wiki


class SmartChat:
    def chat(self, system, user):
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
    })
    return TestClient(app), wiki, store


def test_health(api_client):
    client, _, _ = api_client
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": "0.1.0"}


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
    monkeypatch.setattr("memoria.web.app.load_settings", lambda: current)
    monkeypatch.setattr("memoria.web.app.save_settings", saved.append)

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

    monkeypatch.setattr("memoria.web.app.load_settings", load_current)
    monkeypatch.setattr("memoria.web.app.save_settings", save_current)

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

    monkeypatch.setattr("memoria.web.app.load_settings", load_current)
    monkeypatch.setattr("memoria.web.app.save_settings", save_current)

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
    resp = client.post("/api/config/models", json={"base_url": "https://api.deepseek.com/v1", "api_key": "sk-xxx"})
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
            "llm_api_key": "sk-1234",
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
    items = resp.json()["triages"]
    assert len(items) == 2

    # m1 is OTP verification -> must be protected
    otp_item = next(i for i in items if i["id"] == "m1")
    assert otp_item["protected"] is True
    assert otp_item["can_archive"] is False

    # m2 is marketing -> candidate
    mkt_item = next(i for i in items if i["id"] == "m2")
    assert mkt_item["protected"] is False

    # Attempt to archive m1 (protected) + m2 (marketing)
    arch_resp = client.post(
        "/api/mail/archive",
        json={"confirmed_ids": ["m1", "m2"]},
    )
    assert arch_resp.status_code == 200
    arch_data = arch_resp.json()
    # Red line: m1 must be blocked from archiving!
    assert "m1" in arch_data["blocked"]
    assert "m2" in arch_data["archived"]

    # Confirmed candidates are single-use.
    replay = client.post("/api/mail/archive", json={"confirmed_ids": ["m2"]}).json()
    assert replay["archived"] == []
    assert "m2" in replay["blocked"]


def test_mail_archive_rejects_ids_without_fresh_triage(api_client):
    client, _, _ = api_client

    without_triage = client.post("/api/mail/archive", json={"confirmed_ids": ["m2"]})
    assert without_triage.status_code == 200
    assert without_triage.json()["archived"] == []
    assert "m2" in without_triage.json()["blocked"]

    assert client.get("/api/mail/triage").status_code == 200
    unknown = client.post("/api/mail/archive", json={"confirmed_ids": ["unknown"]})
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

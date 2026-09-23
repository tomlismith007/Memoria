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


def test_config_endpoints(api_client):
    client, _, _ = api_client
    get_resp = client.get("/api/config")
    assert get_resp.status_code == 200
    cfg = get_resp.json()
    assert "llm_base_url" in cfg
    assert "demo_mode" in cfg

    post_resp = client.post(
        "/api/config",
        json={
            "llm_base_url": "https://api.deepseek.com/v1",
            "llm_api_key": "sk-1234567890",
            "llm_model": "deepseek-chat",
            "embed_base_url": "https://api.deepseek.com/v1",
            "embed_api_key": "sk-1234567890",
            "embed_model": "text-embedding-3-small",
            "demo_mode": False,
        },
    )
    assert post_resp.status_code == 200
    assert post_resp.json()["status"] == "ok"


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

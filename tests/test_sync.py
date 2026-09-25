"""feat-008: dual-write, hybrid query, synthesis write-back. Offline."""

from memoria.rag import ChromaStore, FakeEmbedder, ingest_document
from memoria.sync import archive_fact, archive_qa, dual_ingest, hybrid_answer
from memoria.wiki import Wiki


class ScriptedChat:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, system, user):
        self.calls.append((system, user))
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]


def _env(tmp_path):
    store = ChromaStore(path=str(tmp_path / "chroma"))
    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    return store, wiki


def test_dual_ingest_feeds_both_pipelines(tmp_path):
    store, wiki = _env(tmp_path)
    src = tmp_path / "notice.md"
    src.write_text("服务 A 将于 2027-01-01 到期，请提前续费。", encoding="utf-8")
    llm = ScriptedChat("## [[服务到期]]\n# 服务到期\n\n2027 年到期。\n")
    res = dual_ingest(str(src), store, FakeEmbedder(), wiki, llm)
    assert res.chunks > 0 and store.count() > 0  # vector side
    assert res.wiki_pages == ["服务到期"]  # wiki side
    assert "[[服务到期]]" in (wiki.read_page("index") or "")


def test_hybrid_wiki_sufficient_skips_rag(tmp_path):
    store, wiki = _env(tmp_path)
    wiki.write_page("服务到期", "# 服务到期\n\n2027 年到期。\n")
    wiki.build_index()
    llm = ScriptedChat("[[服务到期]]", "服务 A 2027 年到期。[[服务到期]]", "充分")
    ans = hybrid_answer("服务 A 何时到期", wiki, llm, store, FakeEmbedder())
    assert ans.source == "wiki"
    assert ans.wiki_pages == ["服务到期"]
    assert ans.citations == [] and store.count() == 0  # RAG never touched
    assert ans.citations_verified is True  # wiki answer carries [[页名]]


def test_hybrid_flags_unsourced_wiki_answer(tmp_path):
    store, wiki = _env(tmp_path)
    wiki.write_page("服务到期", "# 服务到期\n\n2027 年到期。\n")
    wiki.build_index()
    llm = ScriptedChat("[[服务到期]]", "服务 A 2027 年到期。", "充分")  # answer lacks [[页名]]
    ans = hybrid_answer("服务 A 何时到期", wiki, llm, store, FakeEmbedder())
    assert ans.source == "wiki"
    assert ans.citations_verified is False


def test_hybrid_falls_back_to_rag_for_details(tmp_path):
    store, wiki = _env(tmp_path)
    src = tmp_path / "raw.md"
    src.write_text("服务 A 将于 2027-01-01 到期，续费链接为 https://x 。" * 5, encoding="utf-8")
    ingest_document(str(src), store, FakeEmbedder(), chunk_size=60, chunk_overlap=5)
    wiki.write_page("服务到期", "# 服务到期\n\n2027 年到期。\n")
    wiki.build_index()
    llm = ScriptedChat(
        "[[服务到期]]",  # wiki select
        "服务 A 2027 年到期。[[服务到期]]",  # wiki answer
        "补充",  # gate: needs details
        "续费链接为 https://x 。[1]",  # rag answer
    )
    ans = hybrid_answer("续费链接是什么", wiki, llm, store, FakeEmbedder())
    assert ans.source == "rag+wiki"
    assert "补充细节" in ans.text and "https://x" in ans.text
    assert len(ans.citations) == 1  # rag citations carried through
    assert ans.citations_verified is True  # both halves carry sources


def test_hybrid_requires_both_halves_cited(tmp_path):
    store, wiki = _env(tmp_path)
    src = tmp_path / "raw.md"
    src.write_text("服务 A 将于 2027-01-01 到期，续费链接为 https://x 。" * 5, encoding="utf-8")
    ingest_document(str(src), store, FakeEmbedder(), chunk_size=60, chunk_overlap=5)
    wiki.write_page("服务到期", "# 服务到期\n\n2027 年到期。\n")
    wiki.build_index()
    llm = ScriptedChat(
        "[[服务到期]]",
        "服务 A 2027 年到期。",  # wiki half: no [[页名]]
        "补充",
        "续费链接为 https://x 。[1]",
    )
    ans = hybrid_answer("续费链接是什么", wiki, llm, store, FakeEmbedder())
    assert ans.citations_verified is False  # rag half cited, wiki half not


def test_archive_qa_creates_synthesis_page(tmp_path):
    _, wiki = _env(tmp_path)
    name = archive_qa("服务 A 何时到期/续费？", "2027 年到期。[1]", [], wiki)
    assert "/" not in name  # question with "/" sanitized, write_page-safe
    body = wiki.read_page(name) or ""
    assert "## 回答" in body and "## 来源" in body
    assert f"[[{name}]]" in (wiki.read_page("index") or "")


def test_archive_fact_appends_and_dedups(tmp_path):
    _, wiki = _env(tmp_path)
    assert archive_fact("服务到期", "服务 A 到期日 2027-01-01", "mail:m9", wiki) is True
    assert archive_fact("服务到期", "服务 A 到期日 2027-01-01", "mail:m9", wiki) is False
    body = wiki.read_page("服务到期") or ""
    assert body.count("2027-01-01") == 1

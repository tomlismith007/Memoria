"""feat-005: wiki ops. Offline — FakeChat + scripted replies."""

import pytest

from memoria.llm import FakeChat
from memoria.wiki import Wiki, ingest, lint, query


class ScriptedChat:
    """Reply in call order; records prompts."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def chat(self, system, user):
        self.calls.append((system, user))
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]


@pytest.fixture
def wiki(tmp_path):
    w = Wiki(tmp_path / "kb")
    w.ensure_layout()
    return w


def test_ingest_writes_pages_rebuilds_index_logs(wiki):
    llm = FakeChat(
        "## [[服务到期]]\n# 服务到期\n\n服务 A 2027 年到期。见 [[续费]]。\n\n"
        "## [[续费]]\n# 续费\n\n提前 30 天续费。\n"
    )
    updated = ingest("服务 A 2027-01-01 到期。", "raw/notice.txt", wiki, llm)
    assert updated == ["服务到期", "续费"]
    assert "[[续费]]" in (wiki.read_page("服务到期") or "")
    assert "- [[服务到期]] -> [[续费]]" in (wiki.read_page("index") or "")
    assert "ingest raw/notice.txt" in (wiki.read_page("log") or "")


def test_ingest_caps_at_max_pages(wiki):
    body = "".join(f"## [[P{i}]]\n内容{i}\n\n" for i in range(12))
    updated = ingest("材料", "raw/x.txt", wiki, FakeChat(body), max_pages=10)
    assert len(updated) == 10
    assert wiki.read_page("P10") is None  # 11th+ page dropped
    assert "超出上限" in (wiki.read_page("log") or "")


def test_ingest_ignores_garbage_output(wiki):
    updated = ingest("材料", "raw/x.txt", wiki, FakeChat("这里没有页面分节，随便聊聊。"))
    assert updated == []
    assert wiki.list_pages() == []


def test_query_index_first_then_deep(wiki):
    wiki.write_page("服务到期", "# 服务到期\n\n2027 年到期。\n")
    wiki.write_page("天气", "# 天气\n\n晴。\n")
    wiki.build_index()
    llm = ScriptedChat("[[服务到期]]", "服务 A 2027 年到期。[[服务到期]]")
    ans = query("服务 A 何时到期", wiki, llm)
    assert ans.pages == ["服务到期"]
    assert "目录" in llm.calls[0][1]  # first call sees the index
    assert "2027 年到期" in llm.calls[1][1]  # second call sees the page body
    assert "2027" in ans.text


def test_query_unknown_page_names_filtered(wiki):
    wiki.write_page("A", "# A\n\n内容。\n")
    llm = ScriptedChat("[[不存在的页]]\n[[A]]", "答。")
    ans = query("问", wiki, llm)
    assert ans.pages == ["A"]


def test_lint_broken_and_orphans_no_llm(wiki):
    wiki.write_page("A", "# A\n\n见 [[B]] 和 [[ Ghost ]]。\n")
    wiki.write_page("B", "# B\n\n回链 [[A]]。\n")
    wiki.write_page("孤岛", "# 孤岛\n\n无人引用。\n")
    report = lint(wiki)
    assert report.broken == [("A", "Ghost")]
    assert report.orphans == ["孤岛"]
    assert report.contradictions == []


def test_lint_contradictions_via_llm(wiki):
    wiki.write_page("A", "# A\n\n见 [[B]]。\n")
    wiki.write_page("B", "# B\n\n回链 [[A]]。\n")
    report = lint(wiki, llm=FakeChat("YES: A 说免费，B 说收费"))
    assert len(report.contradictions) == 1
    assert "[[A]] vs [[B]]" in report.contradictions[0]

    clean = lint(wiki, llm=FakeChat("NO"))
    assert clean.contradictions == []
    assert clean.broken == []  # A<->B mutually linked, no orphans either
    assert clean.orphans == []

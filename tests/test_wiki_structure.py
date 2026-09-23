"""feat-004: wiki structure. Offline — tmp dir only."""

import pytest

from memoria.wiki import Wiki, extract_links


@pytest.fixture
def wiki(tmp_path):
    w = Wiki(tmp_path / "kb")
    w.ensure_layout()
    return w


def test_layout_and_schema_defaults(wiki):
    assert wiki.raw_dir.is_dir()
    assert wiki.pages_dir.is_dir()
    assert "双向链接" in wiki.schema_file.read_text(encoding="utf-8")
    assert wiki.index_file.exists() and wiki.log_file.exists()


def test_schema_never_overwritten(wiki):
    wiki.schema_file.write_text("我的规范", encoding="utf-8")
    wiki.ensure_layout()
    assert wiki.schema_file.read_text(encoding="utf-8") == "我的规范"


def test_write_read_list_roundtrip(wiki):
    wiki.write_page("服务到期", "# 服务到期\n\n见 [[续费]]。\n")
    assert "[[续费]]" in (wiki.read_page("服务到期") or "")
    assert wiki.list_pages() == ["服务到期"]
    assert wiki.read_page("不存在") is None


def test_extract_links_ordered_unique():
    assert extract_links("[[B]] 和 [[A]] 还有 [[B]]") == ["B", "A"]


def test_build_index_reflects_links(wiki):
    wiki.write_page("B", "# B\n\n见 [[A]]。\n")
    wiki.write_page("A", "# A\n\n无链接。\n")
    content = wiki.build_index()
    assert "- [[A]]\n" in content
    assert "- [[B]] -> [[A]]" in content


def test_append_log(wiki):
    wiki.append_log("新建页面 服务到期")
    log = wiki.log_file.read_text(encoding="utf-8")
    assert "新建页面 服务到期" in log


def test_raw_is_unwritable(wiki):
    # Red line at code level: page names can never escape wiki/.
    for bad in ("../raw/evil", "..\\raw\\evil", "/abs", "a/b", ""):
        with pytest.raises(ValueError):
            wiki.write_page(bad, "x")
    assert list(wiki.raw_dir.glob("*.md")) == []

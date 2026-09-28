"""feat-053: IDF weighting for keyword_score.

Motivation measured in feat-050: a cross-word fragment like 候需 (straddling
时候|需要) is structurally identical to a real word like 提前 under a
dictionary-free bigram tokeniser. It cannot be filtered out by spelling. It CAN
be weighted out: a fragment that appears in every chunk has df≈100% and an IDF
weight near zero, while a real keyword is rare and scores high.

`keyword_score(query, text)` keeps its two-argument signature. The document
frequency table is an optional third input, so existing call sites
(`retrieve`, `wiki/ops._select_relevant`) are unaffected when it is absent.
"""

import math

import pytest

from memoria.rag.retrieve import (
    DocumentFrequency,
    combined_score,
    keyword_score,
    retrieve,
)


def test_idf_penalises_ubiquitous_tokens():
    """A token in every document must score below a token in one document."""
    df = DocumentFrequency.from_documents(
        ["到期 到期 到期", "到期 到期 财务", "财务 报销", "预算 审批"]
    )
    common = df.weight("到期")  # present in 2 of 4
    rare = df.weight("报销")  # present in 1 of 4
    assert common < rare


def test_a_token_in_every_document_weighs_the_least():
    """Smoothed IDF floors at 1.0 (the classic +1 offset), not at zero.

    What matters is the ordering, not the absolute floor: a token present in
    every document must carry the minimum weight so it cannot dominate a match.
    """
    df = DocumentFrequency.from_documents(["到期 续费 财务"] * 5)
    ubiquitous = df.weight("到期")
    assert ubiquitous == pytest.approx(1.0)
    rare = DocumentFrequency.from_documents(["到期"] + ["财务"] * 4).weight("到期")
    assert ubiquitous < rare


def test_idf_scores_a_rare_keyword_above_a_common_one():
    """The feat-050 failure mode: 到期 must beat filler that appears everywhere."""
    docs = [
        "服务将于 2027 年 1 月 1 日到期。",
        "服务将于 2028 年 1 月 1 日到期。",
        "本表格记录各项费用与流程说明。",
        "本表格记录报销与审批的相关信息。",
    ]
    df = DocumentFrequency.from_documents(docs)
    query = "服务什么时候到期"
    target = docs[0]
    filler = "本表格记录各项费用与流程说明。"

    scored_target = keyword_score(query, target, df)
    scored_filler = keyword_score(query, filler, df)
    assert scored_target > scored_filler, (
        "IDF must let a document with the real keyword outrank one that only "
        "shares filler characters"
    )


def test_idf_is_monotone_in_rarity():
    df = DocumentFrequency.from_documents(
        ["abc abc", "abc def", "def ghi", "ghi jkl", "jkl mno"]
    )
    assert df.weight("mno") > df.weight("abc")
    for token in ("abc", "def", "ghi", "jkl", "mno"):
        assert df.weight(token) >= 1.0


def test_absent_token_keeps_full_weight():
    """A query term with no corpus evidence must not be zeroed out.

    Smoothed IDF gives log((N+1)/1)+1 for an unseen token, which is the maximum —
    correct, because an absent term should never drag a match down.
    """
    df = DocumentFrequency.from_documents(["abc", "def"])
    assert df.weight("zzzz") > df.weight("abc")
    assert df.weight("zzzz") == pytest.approx(math.log(3.0) + 1.0, rel=1e-6)


def test_legacy_two_argument_form_still_works():
    """Existing call sites pass only two args; behaviour must be unchanged."""
    assert keyword_score("苹果 价格", "苹果今日价格") == 1.0
    assert keyword_score("苹果", "汽车介绍") == 0.0
    assert keyword_score("", "anything") == 0.0


def test_score_stays_bounded_with_idf():
    df = DocumentFrequency.from_documents(["苹果 价格 表", "苹果 手机", "价格 便宜"])
    for query in ("苹果", "价格", "苹果 价格", "不存在"):
        for text in ("苹果价格表", "手机", ""):
            assert 0.0 <= keyword_score(query, text, df) <= 1.0


def test_empty_corpus_is_safe():
    df = DocumentFrequency.from_documents([])
    assert 0.0 <= keyword_score("任意", "任意", df) <= 1.0


def test_retrieve_can_be_given_document_frequency(tmp_path):
    """feat-053 wiring: retrieve builds a DF table when a store is available."""
    from memoria.rag import ChromaStore, FakeEmbedder, ingest_document

    store = ChromaStore(path=str(tmp_path / "chroma"))
    embedder = FakeEmbedder()
    for i, body in enumerate(
        ["服务将于 2027 年到期。", "费用与报销流程。", "预算审批说明。", "团队成员名单。"]
    ):
        src = tmp_path / f"d{i}.md"
        src.write_text(body * 10, encoding="utf-8")
        ingest_document(str(src), store, embedder, chunk_size=60, chunk_overlap=5)

    hits = retrieve("什么时候到期", store, embedder, k=8, top_n=4)
    assert hits
    # Scores remain bounded after the change (the combined formula is unchanged).
    for h in hits:
        assert 0.0 <= h["score"] <= 1.0
        assert 0.0 <= h["keyword"] <= 1.0


def test_wiki_selection_prefers_the_relevant_page(tmp_path):
    """feat-040's _select_relevant is the other consumer; it must keep working."""
    from memoria.wiki import Wiki

    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    pages = {}
    for name, body in [
        ("服务到期", "服务 A 将于 2027 年到期，需提前 30 天续费。"),
        ("财务报销", "报销流程与发票管理办法说明。"),
        ("团队介绍", "团队成员名单与入职流程。"),
        ("预算审批", "预算编制与审批权限说明。"),
    ]:
        wiki.write_page(name, f"# {name}\n{body}\n")
        pages[name] = body

    from memoria.wiki.ops import _select_relevant

    picked = _select_relevant(pages, "服务什么时候到期", k=2)
    assert "服务到期" in picked

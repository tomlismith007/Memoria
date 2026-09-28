"""feat-052: tokeniser noise removal.

Character bigrams over a CJK run produce cross-word fragments ("候需", "前续",
"要提") that carry no meaning yet sit in the denominator of `keyword_score`,
diluting real keywords. These tests pin the fixes:

- bigrams are only taken *within* a clause, not across punctuation
- stopword-only runs yield no tokens
- the existing exact-equality assertions on `keyword_score` still hold

The last group is the important one: it guards against a "cleanup" that quietly
changes what a passing retrieval means.
"""

import pytest

from memoria.rag.retrieve import _tokens, combined_score, keyword_score


def test_bigrams_do_not_cross_clause_boundaries():
    """A bigram must never straddle punctuation: 续费。逾期 -> no 费逾."""
    tokens = _tokens("需要续费。逾期有罚则")
    assert "费逾" not in tokens
    assert "需要" in tokens
    assert "续费" in tokens
    assert "逾期" in tokens


def test_known_cross_word_fragments_remain_but_are_documented():
    """Documents the limit feat-052 could not remove.

    Inside a punctuation-free run, bigrams are character-level only: 候需 (a
    fragment straddling 时候|需要) is structurally identical to 提前 (a real
    word). No dictionary-free tokeniser can separate them. feat-053 targets
    these instead — a fragment appearing in nearly every chunk has df≈100% and
    so an IDF weight near zero.
    """
    tokens = _tokens("什么时候需要提前续费")
    assert "么时" in tokens and "候需" in tokens  # the known limitation
    # The real words are present alongside them.
    for good in ("什么", "时候", "需要", "提前", "续费"):
        assert good in tokens


def test_stopword_only_text_yields_no_tokens():
    """Pure filler must not dilute the denominator."""
    assert _tokens("的了是在") == set()
    assert _tokens("的了是在，有内容") & {"了是", "是在", "的了"} == set()


def test_single_cjk_char_is_kept():
    """A one-character CJK query is meaningful; it must not be dropped."""
    assert "书" in _tokens("书")


def test_ascii_tokens_are_unchanged():
    """feat-052 must not disturb the Latin path."""
    assert _tokens("hello world") == {"hello", "world"}
    assert _tokens("Apple iPhone 15") == {"apple", "iphone", "15"}


def test_mixed_script_query():
    tokens = _tokens("用 Python 写 RAG 检索")
    assert "python" in tokens
    assert "rag" in tokens
    assert "写" in tokens or "检索" in tokens


# --- the pre-existing exact assertions must keep holding ---------------------


def test_keyword_score_exact_assertions_still_hold():
    """These are the assertions the rest of the suite already relies on."""
    assert keyword_score("苹果 价格", "苹果今日价格") == 1.0
    assert keyword_score("苹果", "汽车介绍") == 0.0
    assert keyword_score("", "anything") == 0.0


def test_keyword_score_stays_bounded():
    for query in ("苹果 价格", "服务到期", "什么时候到期", "a b c"):
        for text in ("苹果今日价格", "服务将于 2027 年到期", "abc def", ""):
            assert 0.0 <= keyword_score(query, text) <= 1.0


def test_empty_query_tokens_do_not_divide_by_zero():
    assert keyword_score("", "任意文本") == 0.0
    assert keyword_score("的了是在", "任意文本") == 0.0


def test_combined_score_bounded_and_ordered():
    assert 0.0 <= combined_score(0.2, 0.5) <= 1.0
    assert combined_score(None, 1.0, alpha=0.0) == 1.0
    # A better keyword match must never score worse at the same distance.
    assert combined_score(0.3, 0.9) > combined_score(0.3, 0.1)

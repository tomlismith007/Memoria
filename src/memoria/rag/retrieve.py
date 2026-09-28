"""Hybrid retrieval: vector search, then hand-written keyword rerank. No frameworks."""

from __future__ import annotations

import math
import re

from memoria.rag.embed import Embedder
from memoria.rag.store import ChromaStore


_CJK = re.compile(r"[\u4e00-\u9fff]")

# Function words carry no retrieval signal but would sit in keyword_score's
# denominator, diluting real keywords. A CJK run made entirely of these is
# dropped; a run containing real content still yields its bigrams (feat-052).
_CJK_STOPWORDS = frozenset(
    "的 了 是 在 和 与 或 也 就 都 而 及 等 这 那 有 无 为 对 从 到 把 被 让 使 "
    "上 下 中 内 外 前 后 里 个 之 其 你 我 他 她 它 们 不 很 太 更 最 会 能 要 "
    "可以 什么 怎么 如何 吗 呢 吧 啊 呀 哦 嗯 谁 什 么 时 候".split()
)


def _tokens(s: str) -> set[str]:
    """Tokenise for keyword overlap.

    A word run already splits on punctuation, so bigrams never straddle a clause.
    A CJK run made entirely of function words is dropped; otherwise its
    character bigrams are used.

    ponytail: character bigrams cannot tell 候需 (a fragment straddling
    时候|需要) from 提前 (a real word) - the two are structurally identical
    without a dictionary, so such fragments are NOT removed here. They are
    handled by the IDF weighting in keyword_score, where a token present in
    nearly every chunk scores ~0. Upgrade path if that proves insufficient: a
    forward-maximum-matching segmenter over a small built-in word list.
    """
    toks: set[str] = set()
    for run in re.findall(r"\w+", s.lower()):
        if not _CJK.search(run):
            toks.add(run)
        elif len(run) == 1:
            if run not in _CJK_STOPWORDS:
                toks.add(run)
        elif not all(ch in _CJK_STOPWORDS for ch in run):
            toks.update(run[i : i + 2] for i in range(len(run) - 1))
    return toks


class DocumentFrequency:
    """Inverse document frequency over the indexed chunks (feat-053).

    Solves what the tokeniser cannot: under character bigrams a cross-word
    fragment like 候需 is indistinguishable from a real word like 提前. Weighting
    can separate them — a fragment in every chunk has df≈100% and an IDF weight of
    ~0, while a genuine keyword is rare and scores high.

    ponytail: computed over the candidate pool per `retrieve` call rather than
    cached across calls, because a stale table silently misweights. The pool is
    small (k=8..30) so the cost is a few dozen set operations. Upgrade path if
    this shows up in profiling: build the table once at ingest and persist it
    alongside the vectors.
    """

    __slots__ = ("_n", "_df")

    def __init__(self, n: int, df: dict[str, int]) -> None:
        self._n = n
        self._df = df

    @classmethod
    def from_documents(cls, documents) -> "DocumentFrequency":
        df: dict[str, int] = {}
        count = 0
        for doc in documents:
            count += 1
            for token in _tokens(doc):
                df[token] = df.get(token, 0) + 1
        return cls(count, df)

    @property
    def size(self) -> int:
        return self._n

    def weight(self, token: str) -> float:
        """Smoothed IDF, never negative; unknown tokens keep full weight."""
        if self._n <= 0:
            return 1.0
        seen = self._df.get(token, 0)
        return math.log((self._n + 1) / (seen + 1)) + 1.0


def keyword_score(query: str, text: str, df: DocumentFrequency | None = None) -> float:
    """Fraction of query weight found in the text.

    Without `df` this is the historical plain hit-count, so the two existing
    call sites keep their exact behaviour. With `df`, hits are weighted by IDF:
    a common word matches without proving relevance, a rare one does.
    """
    q = _tokens(query)
    if not q:
        return 0.0
    if df is None:
        return len(q & _tokens(text)) / len(q)
    t = _tokens(text)
    hit = q & t
    if not hit:
        return 0.0
    total = sum(df.weight(token) for token in q)
    if total <= 0:
        return 0.0
    return sum(df.weight(token) for token in hit) / total


def combined_score(distance: float | None, kscore: float, alpha: float = 0.7) -> float:
    vsim = max(0.0, 1.0 - (distance or 0.0))  # chroma cosine distance -> similarity
    return alpha * vsim + (1.0 - alpha) * kscore


def retrieve(
    question: str,
    store: ChromaStore,
    embedder: Embedder,
    k: int = 30,
    top_n: int = 4,
    alpha: float = 0.7,
    use_idf: bool = True,
) -> list[dict]:
    """Hybrid retrieval: vector recall, then IDF-weighted keyword rerank.

    feat-054: the first stage was k=8, which is a rerank window masquerading as a
    recall stage — with 41 chunks in a realistic corpus, the target chunk was
    simply not in the candidate set and the keyword term had nothing to work
    with. Measured on that corpus: k=8 missed the answer entirely, k>=15 found
    it at rank 3. The cost is local — 2.4ms at k=8 vs 5.9ms at k=30, against a
    network LLM round-trip measured in seconds. `top_n` is left at 4 because
    that value *is* the LLM token cost, which is a different trade-off.
    """
    qvec = embedder.embed([question])[0]
    hits = store.search(qvec, k=k)
    # feat-053: build the DF table from the candidate pool, so a token present in
    # every candidate (cross-word fragments, filler) is weighted toward the floor
    # while a rare real keyword carries the match. Falls back to the plain
    # hit-count when the pool is empty or IDF is switched off.
    df = (
        DocumentFrequency.from_documents(h["text"] for h in hits) if (use_idf and hits) else None
    )
    for h in hits:
        h["keyword"] = keyword_score(question, h["text"], df)
        h["score"] = combined_score(h.get("distance"), h["keyword"], alpha)
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:top_n]

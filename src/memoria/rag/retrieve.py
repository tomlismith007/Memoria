"""Hybrid retrieval: vector search, then hand-written keyword rerank. No frameworks."""

from __future__ import annotations

import re

from memoria.rag.embed import Embedder
from memoria.rag.store import ChromaStore


_CJK = re.compile(r"[\u4e00-\u9fff]")


def _tokens(s: str) -> set[str]:
    # \w+ runs; CJK runs (no spaces) fall back to character bigrams.
    toks: set[str] = set()
    for run in re.findall(r"\w+", s.lower()):
        if _CJK.search(run) and len(run) > 1:
            toks.update(run[i : i + 2] for i in range(len(run) - 1))
        else:
            toks.add(run)
    return toks


def keyword_score(query: str, text: str) -> float:
    q = _tokens(query)
    return len(q & _tokens(text)) / len(q) if q else 0.0


def combined_score(distance: float | None, kscore: float, alpha: float = 0.7) -> float:
    vsim = max(0.0, 1.0 - (distance or 0.0))  # chroma cosine distance -> similarity
    return alpha * vsim + (1.0 - alpha) * kscore


def retrieve(
    question: str,
    store: ChromaStore,
    embedder: Embedder,
    k: int = 8,
    top_n: int = 4,
    alpha: float = 0.7,
) -> list[dict]:
    qvec = embedder.embed([question])[0]
    hits = store.search(qvec, k=k)
    for h in hits:
        h["keyword"] = keyword_score(question, h["text"])
        h["score"] = combined_score(h.get("distance"), h["keyword"], alpha)
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:top_n]

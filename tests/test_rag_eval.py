"""feat-050: retrieval quality baseline.

Measures whether the right chunk reaches the answer, so later changes to chunking,
tokenising and recall width can be judged instead of guessed.

Method note: an earlier draft used a "flat" embedder (identical vector for every
text) to isolate the keyword term. That was wrong — with identical vectors the
cosine term in `combined_score` is constant across hits, so the final order
degrades to whatever order `store.search` returned and the rerank stops being
measured at all. The tests below therefore use FakeEmbedder (a hashed
bag-of-words) and measure the real hybrid pipeline end to end.

Every chunk carries an identifiable marker so assertions never guess which
document a hit came from. The measured baseline is recorded in
docs/RAG_UPGRADE_PLAN.md rather than frozen as equalities here.
"""

from memoria.rag import ChromaStore, FakeEmbedder, ingest_document, retrieve

# Each document repeats its body so every chunk shares an identifiable marker.
DOCS = {
    "car": "汽车火车飞机轮船。交通工具介绍与保养常识。" * 12,
    "fruit": "苹果香蕉橙子葡萄。水果价格表与挑选建议。" * 12,
    "sub": "服务 A 的订阅将于 2027 年 1 月 1 日到期。需要提前 30 天发起续费。" * 12,
    "weather": "今天天气不错，适合散步。明天有雨，记得带伞。" * 12,
}

# (query, expected tag, keyword identifying the right document)
QUERIES = [
    ("苹果多少钱", "fruit", "苹果"),
    ("交通工具有哪些", "car", "交通工具"),
    ("服务什么时候到期", "sub", "到期"),
]

DOC_IDS: dict[str, str] = {}


def _build(tmp_path, chunk_size=60, chunk_overlap=5):
    store = ChromaStore(path=str(tmp_path / "chroma"))
    DOC_IDS.clear()
    embedder = FakeEmbedder()
    for tag, body in DOCS.items():
        src = tmp_path / f"{tag}.md"
        src.write_text(body, encoding="utf-8")
        result = ingest_document(
            str(src), store, embedder, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        DOC_IDS[result.doc_id] = tag
    return store


def _tag_of(hit) -> str:
    return DOC_IDS.get(hit["doc_id"], "?")


def _rank_of(hits, want_tag):
    for rank, hit in enumerate(hits, 1):
        if _tag_of(hit) == want_tag:
            return rank
    return 0


def test_every_seed_query_reaches_its_document(tmp_path):
    """Baseline: recall@4 must be 3/3 — a regression here is a real regression."""
    store = _build(tmp_path)
    embedder = FakeEmbedder()
    for query, want_tag, want_word in QUERIES:
        hits = retrieve(query, store, embedder, k=8, top_n=4)
        assert hits, f"no hits for {query!r}"
        assert want_word in hits[0]["text"] or any(
            want_word in h["text"] for h in hits
        ), f"{query!r} never surfaced {want_word!r}"
        assert _rank_of(hits, want_tag) > 0, f"{query!r} never reached {want_tag!r}"


def test_hits_are_ranked_by_descending_score(tmp_path):
    store = _build(tmp_path)
    embedder = FakeEmbedder()
    for query, _, _ in QUERIES:
        hits = retrieve(query, store, embedder, k=8, top_n=4)
        scores = [h["score"] for h in hits]
        assert scores == sorted(scores, reverse=True), f"{query!r} not ranked"


def test_widening_the_first_stage_never_loses_a_hit(tmp_path):
    """feat-054's guard: a wider candidate pool must not drop anything."""
    store = _build(tmp_path, chunk_size=40, chunk_overlap=5)
    embedder = FakeEmbedder()
    for query, want_tag, _ in QUERIES:
        wide = retrieve(query, store, embedder, k=30, top_n=4)
        assert _rank_of(wide, want_tag) > 0, (
            f"{query!r}: widening k to 30 lost {want_tag!r}"
        )


def test_paraphrase_ranks_first_with_idf(tmp_path):
    """feat-053's payoff, measured against the feat-050 baseline.

    Before IDF *and* before semantic-boundary chunking, this query ranked the
    right document at position 2: 「什么时候」 tokenises into bigrams (么时/什么/
    时候) sharing no literal overlap with 「将于...到期」, and the fixed-window
    chunker had sliced the sentence so the keyword never matched cleanly.
    feat-051 + feat-053 together close the gap.
    """
    store = _build(tmp_path)
    embedder = FakeEmbedder()
    hits = retrieve("服务什么时候到期", store, embedder, k=8, top_n=4, use_idf=True)
    assert _rank_of(hits, "sub") == 1, (
        "the paraphrased target must rank first; feat-050 measured rank 2"
    )


def test_idf_never_loses_a_hit_relative_to_plain_scoring(tmp_path):
    """IDF is a reweighting, not a filter: it may reorder but must not drop a hit."""
    store = _build(tmp_path)
    embedder = FakeEmbedder()
    for query, want_tag, _ in QUERIES:
        plain = retrieve(query, store, embedder, k=8, top_n=4, use_idf=False)
        idf = retrieve(query, store, embedder, k=8, top_n=4, use_idf=True)
        assert _rank_of(idf, want_tag) > 0, f"{query!r} lost {want_tag!r} under IDF"
        assert _rank_of(idf, want_tag) <= _rank_of(plain, want_tag), (
            f"{query!r}: IDF ranked {want_tag!r} worse than plain scoring"
        )


def _large_corpus(tmp_path, n_filler=37):
    """A corpus with the target buried deep enough that a narrow k cannot see it."""
    store = ChromaStore(path=str(tmp_path / "chroma"))
    embedder = FakeEmbedder()
    bodies = [
        "汽车火车飞机轮船。交通工具介绍与保养常识。" * 8,
        "苹果香蕉橙子葡萄。水果价格表与挑选建议。" * 8,
        "今天天气不错适合散步。明天有雨记得带伞。" * 8,
    ]
    bodies += [f"第{i}份无关文档。内容是会议纪要与日程安排说明。" * 8 for i in range(n_filler)]
    target = "服务 A 的订阅将于 2027 年 1 月 1 日到期。需要提前 30 天发起续费。" * 8
    bodies.insert(20, target)
    for i, body in enumerate(bodies):
        src = tmp_path / f"big{i}.md"
        src.write_text(body, encoding="utf-8")
        ingest_document(str(src), store, embedder, chunk_size=200, chunk_overlap=20)
    return store


def test_narrow_recall_window_finds_nothing(tmp_path):
    """feat-054's motivation, pinned so k cannot silently shrink again.

    With the target buried 20 documents deep, k=8 does not retrieve it at all —
    the answer would say nothing about 到期. This is why k is a recall stage,
    not a rerank window.
    """
    store = _large_corpus(tmp_path)
    embedder = FakeEmbedder()
    narrow = retrieve("服务什么时候到期", store, embedder, k=8, top_n=4)
    assert not any("到期" in h["text"] for h in narrow), (
        "k=8 now reaches the target; feat-054's premise no longer holds — "
        "revisit the default"
    )


def test_default_recall_window_reaches_the_buried_target(tmp_path):
    store = _large_corpus(tmp_path)
    embedder = FakeEmbedder()
    hits = retrieve("服务什么时候到期", store, embedder)  # library default
    assert any("到期" in h["text"] for h in hits), (
        "the default k must retrieve a document 20 positions deep"
    )

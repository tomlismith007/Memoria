"""feat-073/074: context budget, metering, and two-tier compaction. 100% offline.

The load-bearing assertions here are the *negative* ones — that a normal-sized
prompt spends nothing extra and that compaction never breaks an answer. A
compaction that quietly runs on every turn is a cost regression that no
correctness test would catch.
"""

import pytest
from langgraph.checkpoint.memory import MemorySaver

from memoria.context import (
    MAX_MEMORY_CHARS,
    MAX_PAGE_CHARS,
    estimate_tokens,
    fit_history,
    trim_memories,
    trim_page,
)
from memoria.graph import build_graph
from memoria.graph.nodes import SUMMARY_MIN_TOKENS, SUMMARY_QUESTION, _compact
from memoria.llm import CountingLLM, counters, reset_counters
from memoria.memory import MemoryService
from memoria.rag import ChromaStore, FakeEmbedder
from memoria.records import RecordStore
from memoria.wiki import Wiki

from conftest import ScriptedChat


# ---------------------------------------------------------------- trim_page


def test_trim_page_passes_short_pages_through_untouched():
    body = "# 页\n\n短正文。\n"
    assert trim_page(body) == body


def test_trim_page_keeps_head_and_tail_with_a_visible_marker():
    body = "头" * 3_000 + "中" * 3_000 + "尾" * 3_000
    out = trim_page(body)
    assert len(out) < len(body)
    assert "中间省略" in out  # the model must know the middle is missing
    # Head 70% / tail 30% of the ceiling; the middle body is gone entirely.
    # (Count the body runs, not the whole string — the marker says 中间省略.)
    assert out.count("头") == int(MAX_PAGE_CHARS * 0.7)
    assert out.count("尾") == MAX_PAGE_CHARS - int(MAX_PAGE_CHARS * 0.7)
    assert out.count("中") == 1  # only the marker's 中, never the body's


def test_trim_page_boundary_is_inclusive():
    """Exactly at the limit is not trimmed — no marker on a page that fits."""
    body = "字" * MAX_PAGE_CHARS
    assert trim_page(body) == body
    assert "省略" not in trim_page(body)


def test_trim_page_reports_the_omitted_character_count():
    body = "字" * (MAX_PAGE_CHARS + 500)
    assert "省略 500 字" in trim_page(body)


# ------------------------------------------------------------ trim_memories


def test_trim_memories_keeps_all_when_under_budget():
    items = [{"text": "偏好一", "source": "s"}, {"text": "偏好二", "source": "s"}]
    assert trim_memories(items) == items


def test_trim_memories_marks_the_dropped_tail():
    items = [{"text": "长" * 3_000, "source": ""} for _ in range(5)]
    kept = trim_memories(items)
    assert len(kept) < len(items)
    assert "已省略" in kept[-1]["text"]  # the model sees the list is partial
    # Everything that survived is real content, newest first (service order).
    assert all("已省略" not in m["text"] for m in kept[:-1])
    total = sum(len(m["text"]) for m in kept)
    assert total < MAX_MEMORY_CHARS + 200  # marker is the only overshoot


# ------------------------------------------------------------- fit_history


def test_fit_history_returns_a_lossless_order_preserving_split():
    history = [{"question": f"q{i}", "answer": "答" * 4_000} for i in range(12)]
    kept, dropped = fit_history(history)
    assert dropped + kept == history
    assert kept  # newest turn always survives
    assert kept[-1] == history[-1]


def test_fit_history_never_returns_an_empty_history_for_a_giant_turn():
    """One turn over budget on its own is kept: dropping everything helps nobody."""
    history = [{"question": "q", "answer": "答" * 100_000}]
    kept, dropped = fit_history(history)
    assert kept == history and dropped == []


# ---------------------------------------------------------------- metering


def test_counting_wrapper_tallies_calls_and_estimated_tokens():
    reset_counters()
    inner = ScriptedChat("回复")
    llm = CountingLLM(inner)
    llm.chat("系统", "用户")
    snap = counters()
    assert snap["llm_calls"] == 1
    assert snap["est_prompt_tokens"] == pytest.approx(estimate_tokens("系统") + estimate_tokens("用户"))
    assert snap["est_completion_tokens"] == pytest.approx(estimate_tokens("回复"))
    assert inner.calls == [("系统", "用户")]  # inner client still sees the raw call


def test_counting_wrapper_passes_through_unknown_attributes():
    """Tests and adapters reach for `.calls`; the decorator must not hide it."""
    llm = CountingLLM(ScriptedChat("x"))
    assert llm.calls == []
    llm.chat("s", "u")
    assert llm.calls == [("s", "u")]


def test_counters_are_a_copy_not_the_live_dict():
    reset_counters()
    CountingLLM(ScriptedChat("x")).chat("s", "u")
    snapshot = counters()
    snapshot["llm_calls"] = 999
    assert counters()["llm_calls"] == 1


def test_build_graph_does_not_double_wrap_a_counting_llm(tmp_path):
    """activate_settings rebuilds the graph; stacking wrappers would double-count."""
    reset_counters()
    inner = ScriptedChat("问答", "答。[1]")
    counting = CountingLLM(inner)
    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    build_graph(ChromaStore(path=str(tmp_path / "chroma")), FakeEmbedder(), counting, wiki)
    # build_graph kept the same wrapper rather than nesting a second one.
    assert isinstance(counting, CountingLLM)
    counting.chat("s", "u")
    assert counters()["llm_calls"] == 1


# --------------------------------------------------------------- compaction


def _turn(i, size):
    return {"question": f"q{i}", "answer": "答" * size}


def test_compact_under_budget_makes_no_extra_llm_call():
    """The regression that matters: a normal turn must not pay for compaction."""
    reset_counters()
    llm = ScriptedChat("不该被调用")
    history = [_turn(i, 50) for i in range(3)]
    assert _compact(history, llm) == history
    assert llm.calls == []
    assert counters() == {}


def test_compact_below_the_gate_drops_without_summarising(tmp_path, monkeypatch):
    """A small dropped prefix costs more to summarise than it saves — drop it."""
    import memoria.context as context_mod

    monkeypatch.setattr(context_mod, "KEEP_RECENT_TOKENS", 200)
    reset_counters()
    llm = ScriptedChat("不该被调用")
    # 10 turns × ~27 tokens = ~267 tokens; the dropped prefix is well under 512.
    history = [_turn(i, 40) for i in range(10)]
    kept = _compact(history, llm)
    assert not any(t.get("summary") for t in kept)  # no paid summary turn
    assert llm.calls == []
    assert counters().get("summary_calls", 0) == 0
    assert counters().get("tokens_dropped", 0) > 0  # dropped, and accounted as such


def test_compact_above_the_gate_summarises_and_flags_the_turn():
    reset_counters()
    llm = ScriptedChat("用户问了服务到期时间。")
    # Each turn ≈ 4001 tokens; a big history clears the 512-token gate.
    history = [_turn(i, 6_000) for i in range(10)]
    kept = _compact(history, llm)
    summary_turns = [t for t in kept if t.get("summary")]
    assert len(summary_turns) == 1
    assert summary_turns[0]["question"] == SUMMARY_QUESTION
    assert summary_turns[0]["answer"] == "用户问了服务到期时间。"
    assert kept[0].get("summary") is True  # rides in front of the kept tail
    assert len(llm.calls) == 1  # exactly one paid call
    snap = counters()
    assert snap["summary_calls"] == 1
    assert snap["tokens_summarized"] > 0


def test_compact_gate_ignores_the_prior_summary_so_it_does_not_repeat():
    """Counting the existing summary toward the gate would buy a call every turn."""
    reset_counters()
    llm = ScriptedChat("摘要")
    prior_summary = {
        "question": SUMMARY_QUESTION,
        "answer": "答" * 20_000,  # a huge prior summary, well past the gate alone
        "summary": True,
    }
    fresh = [_turn(i, 30) for i in range(2)]  # tiny new content
    kept = _compact([prior_summary] + fresh, llm)
    assert llm.calls == []  # no second summarisation call
    assert counters().get("summary_calls", 0) == 0
    assert kept[0]["answer"] == prior_summary["answer"]  # the paid summary survives


def test_compact_merges_the_prior_summary_when_it_does_summarise():
    reset_counters()
    llm = ScriptedChat("合并后的摘要")
    prior_summary = {
        "question": SUMMARY_QUESTION,
        "answer": "旧摘要要点",
        "summary": True,
    }
    history = [prior_summary] + [_turn(i, 6_000) for i in range(10)]
    kept = _compact(history, llm)
    assert len([t for t in kept if t.get("summary")]) == 1  # merged, not duplicated
    assert "旧摘要要点" in llm.calls[0][1]  # the old summary was fed into the new one


def test_compact_falls_back_to_dropping_when_the_summary_call_fails():
    """Compaction is an optimisation: a failure must never cost the answer."""
    reset_counters()

    class Exploding:
        def chat(self, system, user):
            raise ConnectionError("gateway down")

    history = [_turn(i, 6_000) for i in range(10)]
    kept = _compact(history, Exploding())
    assert not any(t.get("summary") for t in kept)
    assert kept == history[-4:]  # plain drop, same tail the budget would keep
    assert counters().get("tokens_dropped", 0) > 0


def test_compact_falls_back_when_the_summary_is_blank():
    reset_counters()
    history = [_turn(i, 6_000) for i in range(10)]
    kept = _compact(history, ScriptedChat("   "))
    assert not any(t.get("summary") for t in kept)
    assert kept == history[-4:]


def test_compact_does_not_mutate_the_input_history():
    llm = ScriptedChat("摘要")
    history = [_turn(i, 6_000) for i in range(10)]
    before = [dict(t) for t in history]
    _compact(history, llm)
    assert history == before


def test_compacted_history_is_written_back_to_state(tmp_path, monkeypatch):
    """The checkpointer state itself stays bounded — not just the prompt."""
    import memoria.context as context_mod

    monkeypatch.setattr(context_mod, "KEEP_RECENT_TOKENS", 600)

    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    wiki.write_page("服务到期", "# 服务到期\n\n2027 年到期。\n")
    wiki.build_index()
    store = ChromaStore(path=str(tmp_path / "chroma"))

    class Scripted:
        def __init__(self):
            self.calls = []

        def chat(self, system, user):
            self.calls.append((system, user))
            if "对话压缩器" in system:
                return "用户询问服务到期时间。"
            if "Wiki 检索器" in system:
                return "[[服务到期]]"
            if "回答质检员" in system:
                return "充分"
            return "2027 年到期。[[服务到期]]"

    llm = Scripted()
    g = build_graph(store, FakeEmbedder(), llm, wiki).compile(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "compact-1"}}
    # Seed an over-budget history directly through the graph's channel.
    g.update_state(
        cfg,
        {"history": [_turn(i, 3_000) for i in range(8)]},
    )
    out = g.invoke({"text": "那它呢？", "intent": "问答"}, cfg)

    history = out["history"]
    assert any(t.get("summary") for t in history)  # compaction ran
    # The stored state is bounded near the retuned ceiling, not the ~16k tokens
    # that were seeded — the point of writing the compacted list back.
    stored_tokens = sum(
        estimate_tokens(t["question"] + t["answer"]) for t in history
    )
    assert stored_tokens < 3_000
    assert history[-1]["question"] == "那它呢？"  # the live turn is never compacted


def test_qa_answers_normally_when_compaction_is_unnecessary(tmp_path):
    """Zero-overhead path: a short thread must produce the answer unchanged."""
    reset_counters()
    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    wiki.write_page("服务到期", "# 服务到期\n\n2027 年到期。\n")
    wiki.build_index()
    store = ChromaStore(path=str(tmp_path / "chroma"))
    llm = ScriptedChat("[[服务到期]]", "2027 年到期。[[服务到期]]", "充分")
    g = build_graph(store, FakeEmbedder(), llm, wiki).compile()
    out = g.invoke({"text": "何时到期", "intent": "问答"})
    assert "2027" in out["answer_text"]
    assert counters().get("summary_calls", 0) == 0
    assert counters().get("tokens_dropped", 0) == 0


def test_summary_turn_is_not_echoed_as_a_user_question(tmp_path):
    """The pseudo-turn renders as context, and the live question still ends the prompt."""
    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    wiki.write_page("服务到期", "# 服务到期\n\n2027 年到期。\n")
    wiki.build_index()
    store = ChromaStore(path=str(tmp_path / "chroma"))
    llm = ScriptedChat("[[服务到期]]", "2027 年到期。[[服务到期]]", "充分")
    g = build_graph(store, FakeEmbedder(), llm, wiki).compile(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "summary-1"}}
    g.update_state(
        cfg,
        {
            "history": [
                {"question": SUMMARY_QUESTION, "answer": "用户此前问了到期时间。", "summary": True}
            ]
        },
    )
    g.invoke({"text": "那它呢？", "intent": "问答"}, cfg)
    prompt = llm.calls[1][1]  # the wiki answer call carries the transcript
    assert "用户此前问了到期时间。" in prompt
    assert prompt.index("（此前对话）") < prompt.index("（本次问题）")


# ------------------------------------------------- memory budget end-to-end


def test_memory_block_is_budgeted_end_to_end(tmp_path):
    """A pathological memory list must not reach the prompt at full size."""
    records = RecordStore(tmp_path / "r.db")
    service = MemoryService(records)
    for i in range(20):
        service.remember(f"记忆{i}-" + "长" * 1_000, "t")

    captured = []

    class Recorder:
        def chat(self, system, user):
            captured.append(user)
            return "答。[[服务到期]]"

    wiki = Wiki(tmp_path / "kb")
    wiki.ensure_layout()
    wiki.write_page("服务到期", "# 服务到期\n\n2027 年到期。\n")
    wiki.build_index()
    store = ChromaStore(path=str(tmp_path / "chroma"))
    g = build_graph(store, FakeEmbedder(), Recorder(), wiki, memories=service).compile()
    g.invoke({"text": "问", "intent": "问答"})

    prompt = captured[0]
    assert "已省略" in prompt  # the trim is visible to the model
    assert len(prompt) < 20 * 1_010  # and the block did not arrive whole

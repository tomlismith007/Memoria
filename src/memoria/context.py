"""Context budget: one place that decides how many characters a prompt block gets.

feat-073. Before this module the only budgeted block was the qa transcript
(graph/nodes._recent_turns); the wiki page bodies and the memory block were
concatenated with no ceiling at all. Those are the two blocks that grow without
an intrinsic bound, so they are the two that can blow a context window.

This is a leaf module on purpose: `wiki` must not import from `graph` to reach
its own budget, so the estimator and the trimmers live below both.
"""

from __future__ import annotations

# ponytail: character estimate, not a real tokenizer. 1.5 chars/token is the CJK
# side (English would allow ~4), so this errs toward keeping fewer turns than a
# tokenizer would. Upgrade path: swap in tiktoken if a turn ever needs exact
# budgeting against a model-reported context window.
CHARS_PER_TOKEN = 1.5

# The qa transcript ceiling (was graph/nodes.KEEP_RECENT_TOKENS).
KEEP_RECENT_TOKENS = 20_000

# feat-073: per-block ceilings for the two unbounded injections. Sized so a
# normal page or a full 100-memory list passes through untouched — only
# pathological input is trimmed, and then visibly (see the omission markers).
MAX_PAGE_CHARS = 4_000
MAX_MEMORY_CHARS = 4_000

_OMITTED_CHARS = "…[中间省略 {n} 字]…"
_OMITTED_MEMORIES = "…[已省略 {n} 条记忆]…"


def estimate_tokens(text: str) -> float:
    """Estimated token count for a prompt block. Conservative for CJK."""
    return len(text) / CHARS_PER_TOKEN


def trim_page(body: str, limit: int = MAX_PAGE_CHARS) -> str:
    """Head 70% + tail 30% with an explicit marker when a page exceeds the limit.

    Deliberately visible: the model must know the middle is missing, otherwise it
    fills the gap from its own weights and the answer looks cited but is not.
    """
    if len(body) <= limit:
        return body
    head = int(limit * 0.7)
    tail = limit - head
    omitted = len(body) - limit
    return (
        f"{body[:head]}\n{_OMITTED_CHARS.format(n=omitted)}\n{body[len(body) - tail:]}"
    )


def trim_memories(items: list[dict], limit: int = MAX_MEMORY_CHARS) -> list[dict]:
    """Fill memories in order until the character ceiling, then mark the remainder.

    Order is the service's own (newest first), so the newest preferences survive.
    The marker rides in as one extra entry so the model sees that the list is
    partial rather than complete.
    """
    kept: list[dict] = []
    used = 0
    for item in items:
        cost = len(item.get("text", "")) + len(item.get("source", ""))
        if kept and used + cost > limit:
            break
        kept.append(item)
        used += cost
    omitted = len(items) - len(kept)
    if omitted:
        kept = kept + [{"text": _OMITTED_MEMORIES.format(n=omitted), "source": ""}]
    return kept


def fit_history(history: list, budget_tokens: int | None = None) -> tuple[list, list]:
    """Split history into (kept, dropped): newest turns first, oldest dropped.

    Returns the dropped prefix as well as the kept tail — feat-074 summarises the
    prefix instead of discarding it outright. `kept` is ordered oldest-first, the
    same order the prompt and the stored state use.

    `budget_tokens` resolves at call time (not as a bound default) so tests can
    retune the ceiling without reimporting the module.
    """
    if budget_tokens is None:
        budget_tokens = KEEP_RECENT_TOKENS
    kept: list = []
    used = 0.0
    for index, turn in enumerate(reversed(history)):
        cost = estimate_tokens(
            turn.get("question", "") + turn.get("answer", "")
        )
        if used + cost > budget_tokens and kept:
            cut = len(history) - index
            return history[cut:], history[:cut]
        kept.append(turn)
        used += cost
    return list(history), []

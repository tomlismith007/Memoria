"""feat-075: the LLM prompt face is named, frozen, and structurally enforced.

Two separate contracts are locked here:

1. **Cache prefix** — every system prompt is a byte-stable cached prefix (§7.1).
   Editing one silently invalidates the provider cache for that call path, so a
   change must be deliberate and reviewed, not incidental.
2. **Red-line carrier** — the mail prompts are where the "验证码/交易永不自动归档"
   red line is stated to the model. That is an *instructed* constraint (the
   enforced half lives in rules.is_protected and the confirm node), but the
   instruction must still be present, or the model is never told the rule.

The structural test is the important one: it fails if anyone re-inlines a prompt
string, which is how this drift starts.
"""

import ast
from pathlib import Path

import pytest

from memoria.graph.nodes import ROUTER_SYSTEM, SUMMARY_SYSTEM
from memoria.mail.classify import BATCH_SYSTEM, SYSTEM as MAIL_SYSTEM
from memoria.rag.answer import SYSTEM as RAG_SYSTEM
from memoria.sync import GATE_SYSTEM
from memoria.wiki.ops import ANSWER_SYSTEM, INGEST_SYSTEM, LINT_SYSTEM, SELECT_SYSTEM

SRC = Path(__file__).resolve().parents[1] / "src"

# (label, prompt) — the complete LLM system-prompt face: 10 call sites, 10 constants.
# feat-074 added SUMMARY_SYSTEM (the compaction call); it is not one of the four
# feat-075 extracted, but it belongs in this inventory or the "complete face" claim
# is false.
PROMPTS = [
    ("graph.nodes.ROUTER_SYSTEM", ROUTER_SYSTEM),
    ("graph.nodes.SUMMARY_SYSTEM", SUMMARY_SYSTEM),
    ("sync.GATE_SYSTEM", GATE_SYSTEM),
    ("mail.classify.SYSTEM", MAIL_SYSTEM),
    ("mail.classify.BATCH_SYSTEM", BATCH_SYSTEM),
    ("rag.answer.SYSTEM", RAG_SYSTEM),
    ("wiki.ops.INGEST_SYSTEM", INGEST_SYSTEM),
    ("wiki.ops.SELECT_SYSTEM", SELECT_SYSTEM),
    ("wiki.ops.ANSWER_SYSTEM", ANSWER_SYSTEM),
    ("wiki.ops.LINT_SYSTEM", LINT_SYSTEM),
]


def test_prompt_face_is_exactly_ten_constants():
    """A new prompt, or a dropped one, must be a conscious update to this list."""
    assert len(PROMPTS) == 10
    assert len({value for _, value in PROMPTS}) == 10  # no accidental duplicates


@pytest.mark.parametrize("label,prompt", PROMPTS)
def test_prompts_are_clean_single_line_strings(label, prompt):
    """No stray whitespace: the prompt is sent verbatim as the cached block."""
    assert isinstance(prompt, str) and prompt.strip()
    assert prompt == prompt.strip(), f"{label} has leading/trailing whitespace"


# Golden bytes for the four prompts feat-075 extracted out of wiki/ops.py call
# sites. These were inlined, so nothing pinned them; an intentional rewording
# must update this table (and accept the one-off cache miss).
WIKI_PROMPT_BYTES = {
    "INGEST_SYSTEM": "你是 Wiki 维护者。只输出页面内容，无多余解释。",
    "SELECT_SYSTEM": (
        "你是 Wiki 检索器。根据目录选出能回答问题的页面，每行一个（`[[页名]]` 或页名），不要解释。"
    ),
    "ANSWER_SYSTEM": "你是 Wiki 问答助手。只根据提供的页面回答，注明 [[页名]] 来源；答不上就直说。",
    "LINT_SYSTEM": "你是 Wiki 审核员。判断两页是否有实质矛盾，只回 `YES: 原因` 或 `NO`。",
}


def test_extracted_wiki_prompts_are_byte_identical_to_the_originals():
    """feat-075 moved these strings without touching their bytes — prove it."""
    actual = {
        "INGEST_SYSTEM": INGEST_SYSTEM,
        "SELECT_SYSTEM": SELECT_SYSTEM,
        "ANSWER_SYSTEM": ANSWER_SYSTEM,
        "LINT_SYSTEM": LINT_SYSTEM,
    }
    assert actual == WIKI_PROMPT_BYTES


def test_mail_prompts_state_the_archive_red_line():
    """The instructed half of the red line must actually reach the model."""
    for label, prompt in (("SYSTEM", MAIL_SYSTEM), ("BATCH_SYSTEM", BATCH_SYSTEM)):
        assert "验证码/交易" in prompt, f"mail {label} lost the red-line sentence"
        assert "永不自动归档" in prompt, f"mail {label} lost the red-line sentence"
        assert "不可信数据" in prompt, f"mail {label} lost the injection disclaimer"


def test_no_prompt_is_inlined_at_a_call_site():
    """Structural guard: `llm.chat("literal", ...)` is how prompt drift restarts."""
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            is_chat = isinstance(func, ast.Attribute) and func.attr == "chat"
            if not is_chat:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                offenders.append(f"{path.relative_to(SRC.parent)}:{node.lineno}")
    assert not offenders, (
        "inline prompt literal(s) at " + ", ".join(offenders) + " — name them as a "
        "module constant so the cache prefix and red-line text stay auditable"
    )

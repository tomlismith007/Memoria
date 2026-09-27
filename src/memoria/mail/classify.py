"""Two-stage triage: rule layer first, then LLM classify + one-line summary.

Archive is gated twice: only 营销 + unprotected mail becomes a candidate,
and archiving requires explicit human confirmation (confirmed=True).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from memoria.llm import ChatLLM
from memoria.mail.rules import is_protected

CATEGORIES = ("营销", "通知", "待办")
_MARKETING = CATEGORIES[0]
_NOTIFICATION = CATEGORIES[1]
_CATEGORY_PATTERN = "|".join(map(re.escape, CATEGORIES))

SYSTEM = f"你是邮件分类助手。只回两行：`类别：<{'|'.join(CATEGORIES)}>` 和 `摘要：<一句话>`，无多余解释。"


@dataclass
class Email:
    msg_id: str
    subject: str
    sender: str
    snippet: str


@dataclass
class Triage:
    email: Email
    category: str
    summary: str
    protected: bool

    @property
    def archive_candidate(self) -> bool:
        return self.category == _MARKETING and not self.protected


def classify(email: Email, llm: ChatLLM) -> Triage:
    protected = is_protected(email.subject, email.snippet)
    text = llm.chat(
        SYSTEM,
        f"发件人：{email.sender}\n主题：{email.subject}\n内容：{email.snippet}",
    )
    category, summary = _parse(text, fallback=email.snippet)
    return Triage(email=email, category=category, summary=summary, protected=protected)


BATCH_SYSTEM = (
    f"你是邮件分类助手。对每封邮件只回两行，编号与输入一致："
    f"`N. 类别：<{'|'.join(CATEGORIES)}>` 和 `N. 摘要：<一句话>`，无多余解释。"
)


def classify_batch(emails: list[Email], llm: ChatLLM) -> list[Triage]:
    """Classify many emails in one round-trip.

    Red line: the rule layer still runs per email, on its own, before anything the
    LLM returns is trusted. Batching only collapses the LLM call; it never lets a
    single call decide protection for a whole batch. A batch also falls back to
    per-email classify() when it would not actually save a round-trip.
    """
    if not emails:
        return []
    if len(emails) == 1:
        return [classify(emails[0], llm)]

    numbered = "\n\n".join(
        f"[{i}] 发件人：{e.sender}\n主题：{e.subject}\n内容：{e.snippet}"
        for i, e in enumerate(emails, 1)
    )
    replies = _parse_batch(llm.chat(BATCH_SYSTEM, numbered), len(emails))
    return [
        Triage(
            email=email,
            category=replies[i][0],
            summary=replies[i][1],
            protected=is_protected(email.subject, email.snippet),
        )
        for i, email in enumerate(emails)
    ]


def _parse_batch(text: str, count: int) -> list[tuple[str, str]]:
    """Per-index (category, summary). Missing or unparsable lines fall back to 通知.

    Category and summary may arrive on separate lines, so each index accumulates
    across every line that carries its number rather than taking the first one.
    """
    found: dict[int, tuple[str, str]] = {}
    for line in text.splitlines():
        m = re.match(r"\s*\[?(\d+)\]?\s*[.、]?\s*(.*)$", line)
        if not m:
            continue
        idx = int(m.group(1)) - 1
        if not 0 <= idx < count:
            continue
        category, summary = _parse(m.group(2), fallback="")
        prior_category, prior_summary = found.get(idx, (_NOTIFICATION, ""))
        found[idx] = (
            category if category != _NOTIFICATION else prior_category,
            summary or prior_summary,
        )
    return [found.get(i, (_NOTIFICATION, "")) for i in range(count)]


def _parse(text: str, fallback: str) -> tuple[str, str]:
    category, summary = _NOTIFICATION, fallback[:100]
    m = re.search(rf"类别\s*[:：]\s*({_CATEGORY_PATTERN})", text)
    if m:
        category = m.group(1)
    m = re.search(r"摘要\s*[:：]\s*(.+)", text)
    if m:
        summary = m.group(1).strip()
    return category, summary

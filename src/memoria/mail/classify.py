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

SYSTEM = "你是邮件分类助手。只回两行：`类别：<营销|通知|待办>` 和 `摘要：<一句话>`，无多余解释。"


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
        return self.category == "营销" and not self.protected


def classify(email: Email, llm: ChatLLM) -> Triage:
    protected = is_protected(email.subject, email.snippet)
    text = llm.chat(
        SYSTEM,
        f"发件人：{email.sender}\n主题：{email.subject}\n内容：{email.snippet}",
    )
    category, summary = _parse(text, fallback=email.snippet)
    return Triage(email=email, category=category, summary=summary, protected=protected)


def _parse(text: str, fallback: str) -> tuple[str, str]:
    category, summary = "通知", fallback[:100]
    m = re.search(r"类别\s*[:：]\s*(营销|通知|待办)", text)
    if m:
        category = m.group(1)
    m = re.search(r"摘要\s*[:：]\s*(.+)", text)
    if m:
        summary = m.group(1).strip()
    return category, summary

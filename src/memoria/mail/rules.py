"""Rule layer (runs FIRST): verification-code / transaction mail is protected.

Protected = never an archive candidate, no matter what the LLM says.
"""

from __future__ import annotations

import re

CODE_PATTERNS = [
    r"验证码",
    r"verification\s*code",
    r"\botp\b",
    r"动态密码",
    r"确认码",
]

TRANSACTION_PATTERNS = [
    r"订单",
    r"支付",
    r"扣款",
    r"账单",
    r"交易",
    r"入账",
    r"退款",
    r"receipt",
    r"invoice",
    r"\border\b",
    r"payment",
]

_CODE_RE = re.compile("|".join(CODE_PATTERNS), re.I)
_TXN_RE = re.compile("|".join(TRANSACTION_PATTERNS), re.I)


def is_verification(text: str) -> bool:
    return bool(_CODE_RE.search(text))


def is_transaction(text: str) -> bool:
    return bool(_TXN_RE.search(text))


def is_protected(subject: str, body: str) -> bool:
    """Red line: protected mail is NEVER auto-archived."""
    text = f"{subject}\n{body}"
    return is_verification(text) or is_transaction(text)

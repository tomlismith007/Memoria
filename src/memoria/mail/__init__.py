"""AI email triage (lightweight): rules first, LLM second, human confirms archive."""

from memoria.mail.classify import CATEGORIES, Email, Triage, classify, classify_batch
from memoria.mail.gmail import archive, fetch_messages, request_archive
from memoria.mail.rules import is_protected, is_transaction, is_verification

__all__ = [
    "CATEGORIES",
    "Email",
    "Triage",
    "archive",
    "classify",
    "classify_batch",
    "fetch_messages",
    "is_protected",
    "is_transaction",
    "is_verification",
    "request_archive",
]

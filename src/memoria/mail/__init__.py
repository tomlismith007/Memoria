"""AI email triage (lightweight): rules first, LLM second, human confirms archive."""

from memoria.mail.classify import Email, Triage, classify, classify_batch
from memoria.mail.gmail import archive, fetch_messages, request_archive
from memoria.mail.rules import is_protected

__all__ = [
    "Email",
    "Triage",
    "archive",
    "classify",
    "classify_batch",
    "fetch_messages",
    "is_protected",
    "request_archive",
]

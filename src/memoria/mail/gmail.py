"""Gmail API thin wrapper: fetch (read-only) + archive (confirmed only).

Credentials stay with the caller (OAuth flow / token file); this module only
takes an authorized service object. Tests use a duck-typed stub service.
"""

from __future__ import annotations

from memoria.mail.classify import Email, Triage


def fetch_messages(service, query: str = "", max_n: int = 20) -> list[Email]:
    resp = service.users().messages().list(userId="me", q=query, maxResults=max_n).execute()
    out = []
    for m in resp.get("messages", []):
        full = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
        out.append(_to_email(full))
    return out


def _to_email(full: dict) -> Email:
    headers = {h["name"].lower(): h["value"] for h in full["payload"].get("headers", [])}
    return Email(
        msg_id=full["id"],
        subject=headers.get("subject", ""),
        sender=headers.get("from", ""),
        # ponytail: snippet-only; decode full body if classification quality suffers
        snippet=full.get("snippet", ""),
    )


def request_archive(triage: Triage) -> str | None:
    """Eligible msg_id, or None. Protected or non-marketing mail is never eligible."""
    return triage.email.msg_id if triage.archive_candidate else None


def archive(service, msg_id: str, *, confirmed: bool) -> None:
    """Red line: archiving requires explicit human confirmation. No auto-run."""
    if not confirmed:
        raise PermissionError("归档需人工确认：archive(..., confirmed=True)")
    service.users().messages().modify(
        userId="me", id=msg_id, body={"removeLabelIds": ["INBOX"]}
    ).execute()

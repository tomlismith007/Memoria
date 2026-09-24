"""Gmail OAuth authentication helper and service builder."""

from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


def get_gmail_credentials(
    credentials_path: str | Path = "data/credentials.json",
    token_path: str | Path = "data/token.json",
) -> Credentials | None:
    """Load or refresh Gmail OAuth credentials. Returns None if credentials missing."""
    token_file = Path(token_path)
    creds = None

    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        except Exception:
            creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_file.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception:
            pass

    cred_file = Path(credentials_path)
    if not cred_file.exists():
        return None

    flow = InstalledAppFlow.from_client_secrets_file(str(cred_file), SCOPES)
    creds = flow.run_local_server(port=0)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_gmail_service(
    credentials_path: str | Path = "data/credentials.json",
    token_path: str | Path = "data/token.json",
):
    """Build authorized Gmail API client service."""
    creds = get_gmail_credentials(credentials_path, token_path)
    if not creds:
        raise FileNotFoundError(
            f"Gmail OAuth 未完成。请放置客户端凭据至 {credentials_path} 并运行 python scripts/auth_gmail.py"
        )
    return build("gmail", "v1", credentials=creds)

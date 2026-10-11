"""Gmail OAuth authentication helper and service builder.

Token at rest is encrypted with Fernet (feat-069): reading or writing the token
file without TOKEN_ENCRYPTION_KEY set is refused — fail-closed, a plaintext
token never happens again. Legacy plaintext files (pre-feat-066) are only
accepted through the same key gate and migrate to encrypted on the next save.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

# ponytail: one process-wide lock instead of a per-key in-flight map — Memoria
# is single-user/single-process (same assumption as RecordStore). A second
# writer process would need a keyed map plus real file locking.
_REFRESH_LOCK = threading.Lock()

# Refresh 60s before google's own expiry check so a request that starts right
# before expiry doesn't die on a token that expires mid-flight.
_REFRESH_HEADROOM = timedelta(seconds=60)


class TokenEncryptionError(RuntimeError):
    """Fail-closed: token read/write refused because TOKEN_ENCRYPTION_KEY is unset."""


def _fernet() -> Fernet:
    key = os.environ.get("TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise TokenEncryptionError(
            "未设置 TOKEN_ENCRYPTION_KEY，已拒绝读写 Gmail token（fail-closed）。"
            "生成密钥：python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\" 并设为环境变量"
        )
    return Fernet(key.encode("utf-8"))


def _save_token(creds: Credentials, token_path: str | Path) -> None:
    path = Path(token_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fernet = _fernet()  # raises before any plaintext is written to disk
    path.write_bytes(fernet.encrypt(creds.to_json().encode("utf-8")))


def _load_token(token_path: str | Path) -> Credentials | None:
    """Decrypted Credentials, or None when the file is absent."""
    path = Path(token_path)
    if not path.exists():
        return None
    raw = path.read_bytes()
    fernet = _fernet()  # raises when the key is missing — even for legacy plaintext
    try:
        plaintext = fernet.decrypt(raw).decode("utf-8")
    except InvalidToken:
        # Legacy plaintext token (pre-feat-066): accepted only behind the same
        # key gate; the next successful refresh/save migrates it to encrypted.
        try:
            plaintext = raw.decode("utf-8")
            json.loads(plaintext)
        except Exception as e:
            raise TokenEncryptionError("token 文件无法解密：密钥不匹配或文件已损坏") from e
    return Credentials.from_authorized_user_info(json.loads(plaintext), SCOPES)


def _needs_refresh(creds: Credentials) -> bool:
    if not creds.valid:
        return True
    expiry = getattr(creds, "expiry", None)
    if expiry is None:
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry <= datetime.now(timezone.utc) + _REFRESH_HEADROOM


def get_gmail_credentials(
    credentials_path: str | Path = "data/credentials.json",
    token_path: str | Path = "data/token.json",
    interactive: bool = True,
) -> Credentials | None:
    """Load or refresh Gmail OAuth credentials. Returns None if unavailable.

    interactive=False (server startup) never pops the local OAuth browser flow:
    an unusable token simply yields None and the caller degrades gracefully.
    """
    with _REFRESH_LOCK:
        creds = _load_token(token_path)
        if creds is not None and not _needs_refresh(creds):
            return creds
        if creds is not None and creds.refresh_token:
            try:
                creds.refresh(Request())
                _save_token(creds, token_path)
                return creds
            except TokenEncryptionError:
                raise
            except Exception:
                if not interactive:
                    return None
        cred_file = Path(credentials_path)
        if not interactive or not cred_file.exists():
            return None
        flow = InstalledAppFlow.from_client_secrets_file(str(cred_file), SCOPES)
        creds = flow.run_local_server(port=0)
        _save_token(creds, token_path)
        return creds


def get_gmail_service(
    credentials_path: str | Path = "data/credentials.json",
    token_path: str | Path = "data/token.json",
    interactive: bool = True,
):
    """Build authorized Gmail API client service."""
    creds = get_gmail_credentials(credentials_path, token_path, interactive=interactive)
    if not creds:
        raise FileNotFoundError(
            f"Gmail OAuth 未完成。请运行 python scripts/auth_gmail.py 完成授权"
            f"（token 落盘需 TOKEN_ENCRYPTION_KEY 加密，凭据文件：{credentials_path}）"
        )
    return build("gmail", "v1", credentials=creds)

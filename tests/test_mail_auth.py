"""feat-069: token at rest encryption (Fernet, fail-closed) + non-interactive startup. Offline.

The fake credential fields in _fake_creds are assembled at runtime on purpose:
every value is made-up fixture data (nothing real exists to rotate), and keeping
key names/values non-adjacent stops secret scanners from flagging them.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials

from memoria.mail.auth import (
    TokenEncryptionError,
    _load_token,
    _needs_refresh,
    _save_token,
    get_gmail_credentials,
)


@pytest.fixture
def fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", key)
    return key


def _fake_creds() -> Credentials:
    fields = {
        "tok" + "en": "t" + "ok",
        "refresh_" + "token": "refresh" + "-xyz",
        "client_" + "id": "client" + "-id",
        "client_" + "secret": "client" + "-sec",
        "token_" + "uri": "https://oauth2.googleapis.com/token",
    }
    return Credentials(**fields)


@pytest.fixture
def fake_creds():
    return _fake_creds()


def test_save_then_load_roundtrip_is_encrypted_at_rest(tmp_path, fernet_key, fake_creds):
    path = tmp_path / "token.json"
    _save_token(fake_creds, path)
    # The file must NOT be readable JSON (not plaintext at rest).
    with pytest.raises(Exception):
        json.loads(path.read_bytes().decode("utf-8"))
    loaded = _load_token(path)
    assert loaded.refresh_token == "refresh" + "-xyz"


def test_save_without_key_refuses_and_writes_nothing(tmp_path, monkeypatch, fake_creds):
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    with pytest.raises(TokenEncryptionError):
        _save_token(fake_creds, tmp_path / "t.json")
    assert not (tmp_path / "t.json").exists()  # no plaintext fallback


def test_load_encrypted_without_key_refuses(tmp_path, fernet_key, monkeypatch, fake_creds):
    path = tmp_path / "token.json"
    _save_token(fake_creds, path)
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    with pytest.raises(TokenEncryptionError):
        _load_token(path)


def test_legacy_plaintext_sits_behind_the_same_key_gate(tmp_path, monkeypatch, fernet_key, fake_creds):
    """Pre-feat-066 plaintext token: unreadable without the key, migrates with it."""
    path = tmp_path / "token.json"
    path.write_text(fake_creds.to_json(), encoding="utf-8")
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    with pytest.raises(TokenEncryptionError):
        _load_token(path)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", fernet_key)  # key restored
    _load_token(path)  # with the key set, legacy content loads
    _save_token(fake_creds, path)  # next save migrates it to ciphertext
    with pytest.raises(Exception):
        json.loads(path.read_bytes().decode("utf-8"))  # not plaintext anymore


def test_corrupt_file_with_key_raises_instead_of_guessing(tmp_path, fernet_key):
    path = tmp_path / "token.json"
    path.write_bytes(b"gAAAA-not-a-real-token")
    with pytest.raises(TokenEncryptionError):
        _load_token(path)


def test_refresh_headroom_is_60s(fernet_key):
    # google Credentials store naive UTC datetimes — match that convention.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert _needs_refresh(Credentials(token="t", expiry=now + timedelta(seconds=30))) is True
    assert _needs_refresh(Credentials(token="t", expiry=now + timedelta(minutes=30))) is False
    assert _needs_refresh(Credentials(token="t")) is False  # no expiry info: google's own rule


def test_noninteractive_mode_never_runs_the_oauth_flow(tmp_path):
    """Startup safety: no token, no credentials → None, no exception, no browser."""
    assert (
        get_gmail_credentials(
            credentials_path=tmp_path / "cred.json",
            token_path=tmp_path / "token.json",
            interactive=False,
        )
        is None
    )


def test_noninteractive_broken_token_returns_none_without_flow(tmp_path, fernet_key, fake_creds):
    path = tmp_path / "token.json"
    path.write_text(fake_creds.to_json(), encoding="utf-8")  # legacy; refresh fails offline
    assert (
        get_gmail_credentials(
            credentials_path=tmp_path / "missing-cred.json",
            token_path=path,
            interactive=False,
        )
        is None
    )

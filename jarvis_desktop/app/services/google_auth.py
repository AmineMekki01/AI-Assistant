"""Shared Google credential helpers for Gmail, Calendar, and OAuth status."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from google.oauth2.credentials import Credentials
    _GOOGLE_AVAILABLE = True
except ImportError:
    Credentials = None
    _GOOGLE_AVAILABLE = False

from ..core.config import get_settings

TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_TOKEN_PATH = Path.home() / ".jarvis" / "google_token.json"


def token_path() -> Path:
    return Path(os.path.expanduser(os.getenv("GOOGLE_TOKEN_PATH", str(DEFAULT_TOKEN_PATH))))


def clear_google_credentials(path: str | Path | None = None) -> bool:
    """Delete persisted Google credentials if they exist.

    Returns ``True`` when a token file was removed, ``False`` when there was
    nothing to delete.
    """
    token_file = Path(path) if path is not None else token_path()
    if not token_file.exists():
        return False

    token_file.unlink()
    return True


def _scopes_from_payload(payload: dict[str, Any]) -> list[str]:
    scopes = payload.get("scopes")
    if isinstance(scopes, str):
        scopes = scopes.split()
    if isinstance(scopes, list):
        return [str(scope) for scope in scopes if str(scope).strip()]

    scope_str = payload.get("scope") or ""
    return [scope for scope in scope_str.split() if scope]


def _build_credentials_from_payload(payload: dict[str, Any]):
    if not _GOOGLE_AVAILABLE:
        raise RuntimeError("Google client libraries not installed.")

    settings = get_settings()
    client_id = payload.get("client_id") or settings.google_client_id
    client_secret = payload.get("client_secret") or settings.google_client_secret

    if not client_id or not client_secret:
        raise ValueError(
            "Google client credentials are not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )

    token = payload.get("token") or payload.get("access_token") or ""
    refresh_token = payload.get("refresh_token") or ""
    scopes = _scopes_from_payload(payload)

    return Credentials(
        token=token,
        refresh_token=refresh_token,
        token_uri=payload.get("token_uri") or TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes or None,
    )


def load_google_credentials(path: str | Path | None = None, repair: bool = True):
    """Load Google credentials from disk.

    Handles both the authorized-user JSON written by google-auth and the raw
    OAuth token response produced by the callback handler. If a raw token payload
    is encountered and ``repair`` is true, the file is rewritten in the proper
    authorized-user format so future loads work normally.
    """
    if not _GOOGLE_AVAILABLE:
        raise RuntimeError("Google client libraries not installed.")

    token_file = Path(path) if path is not None else token_path()
    if not token_file.exists():
        raise FileNotFoundError(token_file)

    try:
        creds = Credentials.from_authorized_user_file(str(token_file))
        return creds, False
    except Exception:
        raw = json.loads(token_file.read_text())
        creds = _build_credentials_from_payload(raw)
        if repair:
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(creds.to_json())
        return creds, True

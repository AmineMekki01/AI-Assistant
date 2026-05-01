from __future__ import annotations

import json
from types import SimpleNamespace

from app.services import google_auth


class FakeCredentials:
    def __init__(self, token, refresh_token, token_uri, client_id, client_secret, scopes):
        self.token = token
        self.refresh_token = refresh_token
        self.token_uri = token_uri
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes or []
        self.valid = True

    @classmethod
    def from_authorized_user_file(cls, path):
        raise ValueError("not an authorized-user file")

    def to_json(self):
        return json.dumps(
            {
                "token": self.token,
                "refresh_token": self.refresh_token,
                "token_uri": self.token_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scopes": self.scopes,
            }
        )


def test_token_path_respects_environment(monkeypatch, tmp_path):
    token_file = tmp_path / "token.json"
    monkeypatch.setenv("GOOGLE_TOKEN_PATH", str(token_file))

    assert google_auth.token_path() == token_file


def test_load_google_credentials_repairs_raw_payload(temp_home, monkeypatch):
    token_file = temp_home / "custom-token.json"
    token_file.write_text(
        json.dumps(
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "scope": "scope-a scope-b",
                "client_id": "client-id",
                "client_secret": "client-secret",
            }
        )
    )

    monkeypatch.setattr(google_auth, "_GOOGLE_AVAILABLE", True)
    monkeypatch.setattr(google_auth, "Credentials", FakeCredentials)
    monkeypatch.setattr(
        google_auth,
        "get_settings",
        lambda: SimpleNamespace(google_client_id="client-id", google_client_secret="client-secret"),
    )

    creds, repaired = google_auth.load_google_credentials(token_file, repair=True)

    assert repaired is True
    assert creds.token == "access"
    assert creds.refresh_token == "refresh"
    assert creds.scopes == ["scope-a", "scope-b"]
    repaired_payload = json.loads(token_file.read_text())
    assert repaired_payload["client_id"] == "client-id"
    assert repaired_payload["client_secret"] == "client-secret"

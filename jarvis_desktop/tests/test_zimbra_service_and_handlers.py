from __future__ import annotations

import asyncio
import imaplib
import json
import smtplib
from types import SimpleNamespace

import pytest

from app.api.handlers import zimbra as zimbra_handler
from app.services import zimbra


class FakeIMAPConn:
    def __init__(self, search_ids=None, select_ok=True, search_ok=True, fetch_ok=True):
        self.search_ids = search_ids if search_ids is not None else [b"1"]
        self.select_ok = select_ok
        self.search_ok = search_ok
        self.fetch_ok = fetch_ok
        self.login_calls = []
        self.select_calls = []
        self.search_calls = []
        self.fetch_calls = []
        self.logout_called = False

    def login(self, email_addr, password):
        self.login_calls.append((email_addr, password))
        return "OK"

    def select(self, folder, readonly=True):
        self.select_calls.append((folder, readonly))
        return ("OK", [b"1"]) if self.select_ok else ("NO", [])

    def search(self, *args):
        self.search_calls.append(args)
        if not self.search_ok:
            return ("NO", [])
        joined = b" ".join(self.search_ids)
        return ("OK", [joined])

    def fetch(self, msg_id, query):
        self.fetch_calls.append((msg_id, query))
        if not self.fetch_ok:
            return ("NO", [])
        raw = (
            b"From: Support <support@example.com>\n"
            b"Subject: =?utf-8?q?Hello_=F0=9F=91=8B?=\n"
            b"Date: Fri, 01 May 2026 09:00:00 +0000\n\nbody"
        )
        return ("OK", [(None, raw)])

    def logout(self):
        self.logout_called = True
        return "BYE"


class FakeSMTPServer:
    last_instance = None

    def __init__(self, host, port, context=None):
        self.host = host
        self.port = port
        self.context = context
        self.login_calls = []
        self.sendmail_calls = []
        self.quit_called = False
        FakeSMTPServer.last_instance = self

    def login(self, email_addr, password):
        self.login_calls.append((email_addr, password))

    def sendmail(self, sender, recipients, payload):
        self.sendmail_calls.append((sender, recipients, payload))

    def quit(self):
        self.quit_called = True


class FakeIMAP4SSL:
    last_instance = None

    def __init__(self, host, port, ssl_context=None, should_fail=False):
        self.host = host
        self.port = port
        self.ssl_context = ssl_context
        self.should_fail = should_fail
        self.login_calls = []
        self.select_calls = []
        FakeIMAP4SSL.last_instance = self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def login(self, email_addr, password):
        self.login_calls.append((email_addr, password))
        if self.should_fail:
            raise imaplib.IMAP4.error("bad credentials")

    def select(self, folder):
        self.select_calls.append(folder)
        return "OK", [b"1"]


class AsyncJsonRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


async def _passthrough_run(fn, *args):
    return fn(*args)


@pytest.mark.asyncio
async def test_zimbra_config_resolution_and_is_configured(temp_home, monkeypatch):
    settings_path = temp_home / ".jarvis" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "zimbra": {
                    "email": "ui@example.com",
                    "password": "secret",
                    "imapHost": "imap.example.com",
                    "imapPort": 993,
                    "smtpHost": "smtp.example.com",
                    "smtpPort": 465,
                    "smtpSsl": False,
                }
            }
        )
    )

    monkeypatch.setattr(zimbra, "SETTINGS_PATH", settings_path)
    ui_cfg = zimbra._load_ui_settings()
    assert ui_cfg["email"] == "ui@example.com"
    assert ui_cfg["smtpSsl"] is False

    cfg, enabled = zimbra._resolve_config()
    assert enabled is True
    assert cfg["imap_host"] == "imap.example.com"
    assert cfg["smtp_use_ssl"] is False

    monkeypatch.setattr(zimbra, "_load_ui_settings", lambda: {})
    monkeypatch.setenv("ZIMBRA_EMAIL", "env@example.com")
    monkeypatch.setenv("ZIMBRA_PASSWORD", "env-secret")
    monkeypatch.setenv("ZIMBRA_IMAP_HOST", "imap.env.example.com")
    monkeypatch.setenv("ZIMBRA_SMTP_SSL", "true")

    env_cfg, env_enabled = zimbra._resolve_config()
    assert env_enabled is True
    assert env_cfg["email"] == "env@example.com"
    assert env_cfg["smtp_use_ssl"] is True

    monkeypatch.setattr(zimbra, "_resolve_config", lambda: ({}, True))
    assert zimbra.is_configured() is True


@pytest.mark.asyncio
async def test_zimbra_list_search_and_send_success(monkeypatch):
    cfg = {
        "email": "user@example.com",
        "password": "secret",
        "imap_host": "imap.example.com",
        "imap_port": 993,
        "smtp_host": "smtp.example.com",
        "smtp_port": 465,
        "smtp_use_ssl": True,
    }
    conn = FakeIMAPConn(search_ids=[b"1", b"2"])

    monkeypatch.setattr(zimbra, "_resolve_config", lambda: (cfg, True))
    monkeypatch.setattr(zimbra, "_run", _passthrough_run)
    monkeypatch.setattr(zimbra, "_connect_imap", lambda resolved_cfg: conn)
    monkeypatch.setattr(zimbra.smtplib, "SMTP_SSL", lambda host, port, context=None: FakeSMTPServer(host, port, context))

    listed = await zimbra.zimbra_list(max_results=1, only_unread=False)
    assert "📧 1 recent email(s) in INBOX:" in listed
    assert "Support <support@example.com>" in listed
    assert "Hello 👋" in listed
    assert conn.search_calls[0][1] == "ALL"
    assert conn.logout_called is True

    conn.search_ids = [b"3"]
    searched = await zimbra.zimbra_search("invoice", max_results=5)
    assert '📧 1 email(s) matching "invoice" in INBOX:' in searched
    assert conn.search_calls[-1][1] == "TEXT"
    assert conn.logout_called is True

    sent = await zimbra.zimbra_send("recipient@example.com", "Status update", "Body text")
    assert sent == "✓ Email sent to recipient@example.com via smtp.example.com."
    smtp = FakeSMTPServer.last_instance
    assert smtp.login_calls[0] == ("user@example.com", "secret")
    assert smtp.sendmail_calls[0][0] == "user@example.com"
    assert smtp.quit_called is True


@pytest.mark.asyncio
async def test_zimbra_empty_and_error_branches(monkeypatch):
    cfg = {
        "email": "user@example.com",
        "password": "secret",
        "imap_host": "imap.example.com",
        "imap_port": 993,
        "smtp_host": "smtp.example.com",
        "smtp_port": 465,
        "smtp_use_ssl": True,
    }

    monkeypatch.setattr(zimbra, "_resolve_config", lambda: (cfg, False))
    assert "Secondary mailbox is configured but disabled" in await zimbra.zimbra_list()
    assert "Secondary mailbox is configured but disabled" in await zimbra.zimbra_search("test")
    assert "Secondary mailbox is configured but disabled" in await zimbra.zimbra_send("a@example.com", "Subj", "Body")

    monkeypatch.setattr(zimbra, "_resolve_config", lambda: ({"email": "", "password": "", "imap_host": ""}, False))
    assert "Secondary (Zimbra/IMAP) mailbox is not configured" in await zimbra.zimbra_list()

    monkeypatch.setattr(zimbra, "_resolve_config", lambda: (cfg, True))
    monkeypatch.setattr(zimbra, "_run", _passthrough_run)
    monkeypatch.setattr(zimbra, "_connect_imap", lambda resolved_cfg: FakeIMAPConn(search_ids=[]))
    empty_list = await zimbra.zimbra_list(max_results=3, only_unread=True)
    assert empty_list == "No unread emails in INBOX."

    assert await zimbra.zimbra_search("") == "Error: 'query' is required for search action."

    class RaisingConn(FakeIMAPConn):
        def search(self, *args):
            raise imaplib.IMAP4.error("boom")

    monkeypatch.setattr(zimbra, "_connect_imap", lambda resolved_cfg: RaisingConn())
    imap_error = await zimbra.zimbra_search("invoice")
    assert imap_error == "IMAP error: boom"

    def raising_send_sync(*args, **kwargs):
        raise smtplib.SMTPException("smtp down")

    monkeypatch.setattr(zimbra, "_run", lambda fn, *args: raising_send_sync(*args) if fn.__name__ == "_send_sync" else _passthrough_run(fn, *args))
    smtp_error = await zimbra.zimbra_send("a@example.com", "Subject", "Body")
    assert smtp_error == "SMTP error: smtp down"


@pytest.mark.asyncio
async def test_zimbra_handlers_cover_status_and_test_branches(temp_home, monkeypatch):
    status_file = temp_home / ".jarvis" / "zimbra_status.json"
    monkeypatch.setattr(zimbra_handler.Path, "home", lambda: temp_home)

    empty = await zimbra_handler.handle_zimbra_status(SimpleNamespace())
    assert json.loads(empty.text) == {"configured": False, "ok": None}

    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text(json.dumps({"configured": True, "ok": True, "email": "u@example.com"}))
    cached = await zimbra_handler.handle_zimbra_status(SimpleNamespace())
    assert json.loads(cached.text)["configured"] is True

    status_file.write_text("not-json")
    malformed = await zimbra_handler.handle_zimbra_status(SimpleNamespace())
    assert malformed.status == 500
    assert "error" in json.loads(malformed.text)

    class BrokenRequest:
        async def json(self):
            raise ValueError("broken request")

    bad = await zimbra_handler.handle_zimbra_test(BrokenRequest())
    assert bad.status == 400
    assert "Invalid request body" in json.loads(bad.text)["error"]

    missing = await zimbra_handler.handle_zimbra_test(AsyncJsonRequest({"email": "", "password": "", "imapHost": ""}))
    assert missing.status == 400
    assert json.loads(missing.text)["error"] == "Missing email, password, or IMAP host"

    async def json_payload(payload):
        return payload

    monkeypatch.setattr(zimbra_handler, "asyncio", asyncio)
    monkeypatch.setattr(zimbra_handler.imaplib, "IMAP4_SSL", lambda host, port, ssl_context=None: FakeIMAP4SSL(host, port, ssl_context, should_fail=False))

    request = SimpleNamespace(
        json=lambda: json_payload(
            {
                "email": "user@example.com",
                "password": "secret",
                "imapHost": "imap.example.com",
                "imapPort": 993,
                "smtpHost": "smtp.example.com",
                "smtpPort": 465,
                "smtpSsl": True,
            }
        )
    )
    response = await zimbra_handler.handle_zimbra_test(request)
    assert json.loads(response.text)["ok"] is True
    assert json.loads(status_file.read_text())["configured"] is True

    monkeypatch.setattr(zimbra_handler.imaplib, "IMAP4_SSL", lambda host, port, ssl_context=None: FakeIMAP4SSL(host, port, ssl_context, should_fail=True))
    failing = await zimbra_handler.handle_zimbra_test(request)
    payload = json.loads(failing.text)
    assert failing.status == 200
    assert payload["ok"] is False
    assert payload["error"] is not None

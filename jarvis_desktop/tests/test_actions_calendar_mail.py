from __future__ import annotations

import pytest

from app.actions import calendar as calendar_action
from app.actions import mail as mail_action


async def _google_events_stub(**kwargs):
    return "Google events here"


async def _gmail_list_stub(**kwargs):
    return "Gmail inbox summary"


@pytest.mark.asyncio
async def test_calendar_list_and_create_preview(monkeypatch):
    monkeypatch.setattr(calendar_action.gcal_svc, "is_connected", lambda: True)
    monkeypatch.setattr(calendar_action.apple_svc, "is_enabled", lambda: False)
    monkeypatch.setattr(calendar_action.gcal_svc, "gcal_list_events", _google_events_stub)

    listed = await calendar_action.calendar_list(max_results=3)
    assert "Google Calendar" in listed
    assert "Google events here" in listed

    draft = await calendar_action.calendar_create(
        title="Team sync",
        start="2026-05-01T10:00:00+00:00",
        end="2026-05-01T10:30:00+00:00",
        source="google",
    )
    assert draft.startswith("DRAFT EVENT")
    assert "Shall I add it?" in draft


@pytest.mark.asyncio
async def test_calendar_create_confirmed_routes_to_google(monkeypatch):
    calls = {}

    async def fake_create_event(**kwargs):
        calls.update(kwargs)
        return "created"

    monkeypatch.setattr(calendar_action.gcal_svc, "gcal_create_event", fake_create_event)

    result = await calendar_action.calendar_create(
        title="Team sync",
        start="2026-05-01T10:00:00+00:00",
        end="2026-05-01T10:30:00+00:00",
        source="google",
        confirmed=True,
    )

    assert result == "created"
    assert calls["calendar_id"] == "primary"


@pytest.mark.asyncio
async def test_mail_list_and_send_preview(monkeypatch, temp_home):
    token_file = temp_home / ".jarvis" / "google_token.json"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("{}")
    monkeypatch.setattr(mail_action.zimbra_svc, "is_configured", lambda: False)
    monkeypatch.setattr(mail_action.gmail_svc, "gmail_list", _gmail_list_stub)

    listed = await mail_action.mail_list(max_results=2)
    assert "Gmail" in listed
    assert "Gmail inbox summary" in listed

    draft = await mail_action.mail_send(
        to="test@example.com",
        subject="Status update",
        body="Hello there",
    )
    assert draft.startswith("DRAFT")
    assert "Shall I send it?" in draft


@pytest.mark.asyncio
async def test_mail_account_resolution_and_send_routing(monkeypatch, temp_home):
    token_file = temp_home / ".jarvis" / "google_token.json"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("{}")

    monkeypatch.setattr(mail_action, "_google_connected", lambda: True)
    monkeypatch.setattr(mail_action.zimbra_svc, "is_configured", lambda: True)

    resolved_all = mail_action._resolve_accounts(None)
    assert resolved_all == ["gmail", "zimbra"]

    resolved_filtered = mail_action._resolve_accounts(["zimbra"])
    assert resolved_filtered == ["zimbra"]

    monkeypatch.setattr(mail_action, "_google_connected", lambda: False)
    monkeypatch.setattr(mail_action.zimbra_svc, "is_configured", lambda: False)
    assert await mail_action.mail_list() == "Error: No mail accounts connected. Connect Gmail and/or Zimbra in Settings."
    assert await mail_action.mail_search("project") == "Error: No mail accounts connected."

    monkeypatch.setattr(mail_action, "_google_connected", lambda: True)
    monkeypatch.setattr(mail_action.zimbra_svc, "is_configured", lambda: True)

    gmail_calls = {}
    zimbra_calls = {}

    async def fake_gmail_send(**kwargs):
        gmail_calls.update(kwargs)
        return "gmail sent"

    async def fake_zimbra_send(**kwargs):
        zimbra_calls.update(kwargs)
        return "zimbra sent"

    monkeypatch.setattr(mail_action.gmail_svc, "gmail_send", fake_gmail_send)
    monkeypatch.setattr(mail_action.zimbra_svc, "zimbra_send", fake_zimbra_send)

    assert await mail_action.mail_send(to="x@example.com", subject="Hi", body="Body", account="imap") == "Error: Unknown account: imap"
    assert await mail_action.mail_send(to="x@example.com", subject="Hi", body="Body", account="gmail", confirmed=True) == "gmail sent"
    assert gmail_calls == {"to": "x@example.com", "subject": "Hi", "body": "Body"}

    assert await mail_action.mail_send(to="x@example.com", subject="Hi", body="Body", account="zimbra", confirmed=True) == "zimbra sent"
    assert zimbra_calls == {"to": "x@example.com", "subject": "Hi", "body": "Body"}

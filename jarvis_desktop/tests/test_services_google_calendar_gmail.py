from __future__ import annotations

import pytest

from app.services import gcal, gmail


class FakeListResult:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeCalendarEvents:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return FakeListResult(self.payload)

    def insert(self, **kwargs):
        self.calls.append(kwargs)
        return FakeListResult({"htmlLink": "https://calendar.example/event"})


class FakeCalendarService:
    def __init__(self, payload):
        self.events_api = FakeCalendarEvents(payload)

    def events(self):
        return self.events_api


class FakeGmailMessages:
    def __init__(self):
        self.list_calls = []
        self.get_calls = []
        self.send_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return FakeListResult({"messages": [{"id": "m1"}]})

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return FakeListResult(
            {
                "payload": {
                    "headers": [
                        {"name": "Date", "value": "Fri, 01 May 2026 09:29:40 +0000"},
                        {"name": "From", "value": "Support <support@example.com>"},
                        {"name": "Subject", "value": "Hello there"},
                    ]
                }
            }
        )

    def send(self, **kwargs):
        self.send_calls.append(kwargs)
        return FakeListResult({})


class EmptyGmailMessages(FakeGmailMessages):
    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return FakeListResult({"messages": []})


class FakeGmailUsers:
    def __init__(self):
        self.messages_api = FakeGmailMessages()

    def messages(self):
        return self.messages_api


class FakeGmailService:
    def __init__(self):
        self.users_api = FakeGmailUsers()

    def users(self):
        return self.users_api


class EmptyGmailService(FakeGmailService):
    def __init__(self):
        self.users_api = FakeGmailUsers()
        self.users_api.messages_api = EmptyGmailMessages()


@pytest.mark.asyncio
async def test_gcal_list_events_formats_results(monkeypatch):
    service = FakeCalendarService(
        {
            "items": [
                {
                    "summary": "Planning call",
                    "start": {"dateTime": "2026-05-01T10:00:00+00:00"},
                    "end": {"dateTime": "2026-05-01T11:00:00+00:00"},
                    "location": "Zoom",
                }
            ]
        }
    )

    async def fake_service_or_error():
        return service, ""

    monkeypatch.setattr(gcal, "_service_or_error", fake_service_or_error)

    text = await gcal.gcal_list_events(start="2026-05-01T00:00:00+00:00", end="2026-05-02T00:00:00+00:00")
    assert "Planning call" in text
    assert "Zoom" in text
    assert service.events_api.calls[0]["calendarId"] == "primary"


@pytest.mark.asyncio
async def test_gcal_handles_empty_calendar_and_create_event_validation(monkeypatch):
    empty_service = FakeCalendarService({"items": []})

    async def fake_service_or_error():
        return empty_service, ""

    monkeypatch.setattr(gcal, "_service_or_error", fake_service_or_error)

    empty = await gcal.gcal_list_events(calendar_id="work")
    assert "No events found on calendar 'work'" in empty

    assert await gcal.gcal_create_event(title="", start="", end="") == (
        "Error: 'title', 'start' and 'end' are required to create an event."
    )

    created = await gcal.gcal_create_event(
        title="Demo",
        start="2026-05-01T10:00:00",
        end="2026-05-01T11:00:00",
        description="Run through the plan",
        location="Room 2",
        attendees=["a@example.com", ""],
    )
    assert "✓ Created event 'Demo'" in created
    assert empty_service.events_api.calls[1]["body"]["attendees"] == [{"email": "a@example.com"}]


@pytest.mark.asyncio
async def test_gmail_list_and_send_use_fake_service(monkeypatch):
    service = FakeGmailService()

    async def fake_service_or_error():
        return service, ""

    monkeypatch.setattr(gmail, "_service_or_error", fake_service_or_error)

    listed = await gmail.gmail_list(max_results=5, only_unread=True)
    assert "unread email(s)" in listed
    assert "Support <support@example.com>" in listed

    sent = await gmail.gmail_send(to="test@example.com", subject="Hello", body="Body text")
    assert "✓ Email sent to test@example.com" in sent
    assert service.users_api.messages_api.send_calls[0]["userId"] == "me"


@pytest.mark.asyncio
async def test_gmail_empty_result_branches(monkeypatch):
    service = EmptyGmailService()

    async def fake_service_or_error():
        return service, ""

    monkeypatch.setattr(gmail, "_service_or_error", fake_service_or_error)

    unread = await gmail.gmail_list(max_results=5, only_unread=True)
    assert unread == "No unread emails."

    inbox = await gmail.gmail_list(max_results=5, only_unread=False)
    assert inbox == "Gmail inbox is empty for this query."

    found = await gmail.gmail_search("project update")
    assert found == "No emails found for query: project update"


@pytest.mark.asyncio
async def test_gmail_service_error_branch(monkeypatch):
    async def fake_service_or_error():
        return None, "Service unavailable"

    monkeypatch.setattr(gmail, "_service_or_error", fake_service_or_error)

    assert await gmail.gmail_list() == "Error: Service unavailable"
    assert await gmail.gmail_search("anything") == "Error: Service unavailable"
    assert await gmail.gmail_send("a@example.com", "Subject", "Body") == "Error: Service unavailable"

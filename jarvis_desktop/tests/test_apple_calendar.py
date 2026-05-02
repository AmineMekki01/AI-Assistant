from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.api.handlers import apple_calendar as apple_handler
from app.services import apple_calendar as apple_cal


@pytest.mark.asyncio
async def test_apple_calendar_service_preflight_and_list_branches(temp_home, monkeypatch):
    settings_path = temp_home / ".jarvis" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"appleCalendar": {"enabled": True, "defaultCalendar": "Work"}}))

    monkeypatch.setattr(apple_cal, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(apple_cal.sys, "platform", "darwin")

    assert apple_cal.is_enabled() is True
    assert apple_cal._default_calendar() == "Work"
    assert apple_cal._parse_iso("2026-05-01T10:00:00Z").tzinfo is None

    monkeypatch.setattr(apple_cal.sys, "platform", "linux")
    assert await apple_cal.apple_cal_list_calendars() == "Error: Apple Calendar is only available on macOS."

    monkeypatch.setattr(apple_cal.sys, "platform", "darwin")
    monkeypatch.setattr(apple_cal, "is_enabled", lambda: False)
    assert await apple_cal.apple_cal_list_calendars() == (
        "Error: Apple Calendar integration is disabled. Open Settings -> Integrations "
        "-> Apple Calendar and toggle it on."
    )

    monkeypatch.setattr(apple_cal, "is_enabled", lambda: True)

    async def permission_denied(script, timeout=20):
        return False, "", "not allowed to send Apple events"

    monkeypatch.setattr(apple_cal, "_run_osascript", permission_denied)
    assert await apple_cal.apple_cal_list_calendars() == (
        "Error: Calendar access was denied by macOS. Open System Settings -> Privacy & Security "
        "-> Calendars, and enable access for the app running JARVIS (Terminal / VS Code / "
        "iTerm / the JARVIS app). Then try again."
    )

    async def calendars_ok(script, timeout=20):
        return True, "Work, Personal", ""

    monkeypatch.setattr(apple_cal, "_run_osascript", calendars_ok)
    assert await apple_cal.apple_cal_list_calendars() == "Available calendars:\n  • Work\n  • Personal"

    async def calendars_empty(script, timeout=20):
        return True, "", ""

    monkeypatch.setattr(apple_cal, "_run_osascript", calendars_empty)
    assert await apple_cal.apple_cal_list_calendars() == "No calendars found in Calendar.app."


@pytest.mark.asyncio
async def test_apple_calendar_service_events_and_create_branches(temp_home, monkeypatch):
    settings_path = temp_home / ".jarvis" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"appleCalendar": {"enabled": True, "defaultCalendar": "Home"}}))

    monkeypatch.setattr(apple_cal, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(apple_cal.sys, "platform", "darwin")
    monkeypatch.setattr(apple_cal, "is_enabled", lambda: True)

    assert await apple_cal.apple_cal_list_events(start="bad-date") == "Error: invalid date format (Invalid isoformat string: 'bad-date'). Use ISO-8601."
    assert await apple_cal.apple_cal_list_events(start="2026-05-01T10:00:00", end="2026-05-01T09:00:00") == "Error: 'end' must be after 'start'."

    async def list_no_rows(script, timeout=20):
        return True, "", ""

    monkeypatch.setattr(apple_cal, "_run_osascript", list_no_rows)
    no_rows = await apple_cal.apple_cal_list_events(start="2026-05-01T10:00:00", end="2026-05-02T10:00:00")
    assert no_rows == "No Apple Calendar events between 2026-05-01T10:00 and 2026-05-02T10:00."

    captured_scripts = []

    async def list_events_ok(script, timeout=20):
        captured_scripts.append(script)
        return True, (
            "Work|Later meeting|2026-05-01T13:00:00|2026-05-01T14:00:00|Zoom\n"
            "Work|Earlier meeting|2026-05-01T09:00:00|2026-05-01T09:30:00|"
        ), ""

    monkeypatch.setattr(apple_cal, "_run_osascript", list_events_ok)
    events = await apple_cal.apple_cal_list_events(
        start="2026-05-01T08:00:00",
        end="2026-05-01T18:00:00",
        max_results=1,
        calendar='Team "Ops"',
    )
    assert captured_scripts and 'name is "Team \\\"Ops\\\""' in captured_scripts[0]
    assert events.startswith("1 Apple Calendar event(s):")
    assert "Earlier meeting" in events
    assert "Zoom" not in events

    assert await apple_cal.apple_cal_create_event(title="", start="", end="") == "Error: 'title', 'start' and 'end' are required to create an event."
    assert await apple_cal.apple_cal_create_event(title="Demo", start="bad", end="2026-05-01T11:00:00") == "Error: invalid date format (Invalid isoformat string: 'bad'). Use ISO-8601."
    assert await apple_cal.apple_cal_create_event(title="Demo", start="2026-05-01T11:00:00", end="2026-05-01T10:00:00") == "Error: 'end' must be after 'start'."

    async def create_permission_error(script, timeout=20):
        return False, "", "not allowed to send Apple events"

    monkeypatch.setattr(apple_cal, "_run_osascript", create_permission_error)
    assert await apple_cal.apple_cal_create_event(title="Demo", start="2026-05-01T10:00:00", end="2026-05-01T11:00:00") == (
        "Error: Calendar access was denied by macOS. Open System Settings -> Privacy & Security "
        "-> Calendars, and enable access for the app running JARVIS (Terminal / VS Code / "
        "iTerm / the JARVIS app). Then try again."
    )

    async def create_generic_error(script, timeout=20):
        return False, "", "boom"

    monkeypatch.setattr(apple_cal, "_run_osascript", create_generic_error)
    assert await apple_cal.apple_cal_create_event(title="Demo", start="2026-05-01T10:00:00", end="2026-05-01T11:00:00") == "Error creating event: boom"

    create_scripts = []

    async def create_no_calendar(script, timeout=20):
        create_scripts.append(script)
        return True, "ERR_NO_CALENDAR", ""

    monkeypatch.setattr(apple_cal, "_run_osascript", create_no_calendar)
    missing_calendar = await apple_cal.apple_cal_create_event(
        title='Team "sync"',
        start="2026-05-01T10:00:00",
        end="2026-05-01T11:00:00",
        notes='Use the \\slash command',
        location='Room "B"',
    )
    assert missing_calendar == (
        "Error: calendar 'Home' not found in Calendar.app. List the calendars first to see available names."
    )
    assert 'summary:"Team \\\"sync\\\""' in create_scripts[0]
    assert 'description:"Use the \\\\slash command"' in create_scripts[0]
    assert 'location:"Room \\\"B\\\""' in create_scripts[0]

    async def create_ok(script, timeout=20):
        return True, "Team sync | Home", ""

    monkeypatch.setattr(apple_cal, "_run_osascript", create_ok)
    created = await apple_cal.apple_cal_create_event(
        title="Team sync",
        start="2026-05-01T10:00:00",
        end="2026-05-01T11:00:00",
        calendar="Home",
    )
    assert created == "✓ Created Apple Calendar event: Team sync | Home"


@pytest.mark.asyncio
async def test_apple_calendar_handlers_cover_probe_status_and_list_branches(temp_home, monkeypatch):
    monkeypatch.setattr(apple_handler.sys, "platform", "linux")
    assert (await apple_handler.handle_apple_calendar_test(SimpleNamespace())).status == 400
    assert (await apple_handler.handle_apple_calendar_status(SimpleNamespace())).text == '{"enabled": false, "available": false, "ok": null}'
    assert (await apple_handler.handle_apple_calendar_list(SimpleNamespace())).text == '{"calendars": [], "error": "Only available on macOS"}'

    monkeypatch.setattr(apple_handler.sys, "platform", "darwin")

    async def run_probe_success(*args, **kwargs):
        return True, None

    monkeypatch.setattr(apple_handler, "_applescript_probe", lambda: (True, None))
    response = await apple_handler.handle_apple_calendar_test(SimpleNamespace())
    assert response.status == 200
    assert json.loads(response.text) == {"ok": True, "error": None}

    status_path = temp_home / ".jarvis" / "apple_calendar_status.json"
    saved = json.loads(status_path.read_text())
    assert saved["enabled"] is True
    assert saved["available"] is True
    assert saved["ok"] is True

    monkeypatch.setattr(apple_handler, "_applescript_probe", lambda: (False, "probe failed"))
    response = await apple_handler.handle_apple_calendar_test(SimpleNamespace())
    assert json.loads(response.text) == {"ok": False, "error": "probe failed"}

    status_path.write_text("not-json")
    status = await apple_handler.handle_apple_calendar_status(SimpleNamespace())
    payload = json.loads(status.text)
    assert payload["enabled"] is True
    assert payload["ok"] is None

    monkeypatch.setattr(apple_handler, "_applescript_list_calendars", lambda: (["Work", "Home"], None))
    listed = await apple_handler.handle_apple_calendar_list(SimpleNamespace())
    assert json.loads(listed.text) == {"calendars": ["Work", "Home"], "error": None}

    monkeypatch.setattr(apple_handler, "_applescript_list_calendars", lambda: ([], "boom"))
    listed_error = await apple_handler.handle_apple_calendar_list(SimpleNamespace())
    assert json.loads(listed_error.text) == {"calendars": [], "error": "boom"}

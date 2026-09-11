"""Tests for reminders tools and handlers."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest


@pytest.fixture(autouse=True)
def patch_db_path(temp_home, monkeypatch):
    from app.tools import reminders
    from app.api.handlers import reminders as rh

    db_path = temp_home / ".jarvis" / "reminders.db"
    monkeypatch.setattr(reminders, "_DB_PATH", db_path)
    monkeypatch.setattr(rh, "_DB_PATH", db_path)
    yield db_path


class TestReminderCreate:
    async def test_creates_reminder_with_delay(self):
        from app.tools.reminders import reminder_create

        result = await reminder_create("Call Marie", delay="20 minutes")
        assert "Reminder set" in result
        assert "Call Marie" in result
        assert "20 minutes" in result

    async def test_creates_reminder_with_absolute_time(self):
        from app.tools.reminders import reminder_create

        future = (datetime.now().astimezone() + timedelta(hours=2)).isoformat()
        result = await reminder_create("Meeting", absolute_time=future)
        assert "Reminder set" in result
        assert "Meeting" in result

    async def test_rejects_empty_text(self):
        from app.tools.reminders import reminder_create

        result = await reminder_create("")
        assert "Error" in result

    async def test_rejects_past_time(self):
        from app.tools.reminders import reminder_create

        past = (datetime.now().astimezone() - timedelta(hours=1)).isoformat()
        result = await reminder_create("Past event", absolute_time=past)
        assert "Error" in result
        assert "future" in result.lower()

    async def test_defaults_to_15_minutes(self):
        from app.tools.reminders import reminder_create, reminder_list

        await reminder_create("Default delay")
        result = await reminder_list()
        assert "Default delay" in result


class TestReminderList:
    async def test_empty_list(self):
        from app.tools.reminders import reminder_list

        result = await reminder_list()
        assert "No upcoming reminders" in result

    async def test_lists_upcoming(self):
        from app.tools.reminders import reminder_create, reminder_list

        await reminder_create("Task A", delay="1 hour")
        await reminder_create("Task B", delay="2 hours")
        result = await reminder_list()
        assert "Upcoming reminders (2)" in result
        assert "Task A" in result
        assert "Task B" in result

    async def test_hides_reminded_items(self):
        from app.tools.reminders import reminder_create, _mark_reminded

        # Create a reminder that is already past due
        from app.tools.reminders import _conn
        rid = "test-past"
        conn = _conn()
        conn.execute(
            "INSERT INTO reminders (id, text, due_at, created_at, reminded) VALUES (?, ?, ?, ?, ?)",
            (rid, "Past task", (datetime.now().astimezone() - timedelta(minutes=1)).isoformat(), datetime.now().astimezone().isoformat(), 1),
        )
        conn.commit()
        conn.close()

        from app.tools.reminders import reminder_list
        result = await reminder_list()
        assert "Past task" not in result


class TestReminderCancel:
    async def test_cancels_by_number(self):
        from app.tools.reminders import reminder_create, reminder_cancel, reminder_list

        await reminder_create("Cancel me", delay="1 hour")
        result = await reminder_cancel("1")
        assert "Cancelled" in result
        list_result = await reminder_list()
        assert "No upcoming reminders" in list_result

    async def test_cancels_by_text(self):
        from app.tools.reminders import reminder_create, reminder_cancel, reminder_list

        await reminder_create("Important call")
        result = await reminder_cancel("important call")
        assert "Cancelled" in result
        list_result = await reminder_list()
        assert "No upcoming reminders" in list_result

    async def test_not_found(self):
        from app.tools.reminders import reminder_cancel

        result = await reminder_cancel("nonexistent")
        assert "Could not find" in result


class TestReminderSnooze:
    async def test_snoozes_reminder(self):
        from app.tools.reminders import reminder_create, reminder_snooze, reminder_list

        await reminder_create("Snooze me", delay="5 minutes")
        result = await reminder_snooze("1", minutes=10)
        assert "Snoozed" in result
        assert "10 minutes" in result


class TestDueNotes:
    def test_returns_due_items(self, patch_db_path):
        from app.tools.reminders import _conn, _due_notes

        conn = _conn()
        now = datetime.now().astimezone()
        conn.execute(
            "INSERT INTO reminders (id, text, due_at, created_at, reminded) VALUES (?, ?, ?, ?, ?)",
            ("due-1", "Due task", (now - timedelta(minutes=1)).isoformat(), now.isoformat(), 0),
        )
        conn.execute(
            "INSERT INTO reminders (id, text, due_at, created_at, reminded) VALUES (?, ?, ?, ?, ?)",
            ("future-1", "Future task", (now + timedelta(hours=1)).isoformat(), now.isoformat(), 0),
        )
        conn.commit()
        conn.close()

        due = _due_notes()
        texts = [d["text"] for d in due]
        assert "Due task" in texts
        assert "Future task" not in texts

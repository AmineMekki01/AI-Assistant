"""Tests for quick_notes tools and handlers."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest


@pytest.fixture(autouse=True)
def patch_notes_path(temp_home, monkeypatch):
    from app.tools import quick_notes
    from app.api.handlers import quick_notes as qn_handlers

    path = temp_home / ".jarvis" / "quick_notes.json"
    monkeypatch.setattr(quick_notes, "_NOTES_PATH", path)
    monkeypatch.setattr(qn_handlers, "_NOTES_PATH", path)
    yield path


class TestQuickNoteCreate:
    async def test_creates_note(self):
        from app.tools.quick_notes import quick_note_create

        result = await quick_note_create("Buy milk")
        assert "Saved quick note" in result
        assert "Buy milk" in result

    async def test_rejects_empty_text(self):
        from app.tools.quick_notes import quick_note_create

        result = await quick_note_create("")
        assert "Error" in result

    async def test_rejects_whitespace_only(self):
        from app.tools.quick_notes import quick_note_create

        result = await quick_note_create("   ")
        assert "Error" in result


class TestQuickNoteList:
    async def test_empty_list(self):
        from app.tools.quick_notes import quick_note_list

        result = await quick_note_list()
        assert "No pending quick notes" in result

    async def test_lists_pending_notes(self):
        from app.tools.quick_notes import quick_note_create, quick_note_list

        await quick_note_create("Note one")
        await quick_note_create("Note two")
        result = await quick_note_list()
        assert "Pending quick notes (2)" in result
        assert "Note one" in result
        assert "Note two" in result

    async def test_hides_done_notes(self):
        from app.tools.quick_notes import quick_note_create, quick_note_done, quick_note_list

        await quick_note_create("Note one")
        await quick_note_create("Note two")
        await quick_note_done("1")
        result = await quick_note_list()
        assert "Note one" not in result
        assert "Note two" in result

    async def test_hides_expired_notes(self, patch_notes_path):
        from app.tools.quick_notes import quick_note_create, quick_note_list, _load_notes, _save_notes

        await quick_note_create("Fresh note")
        # Manually make a note expired
        notes = _load_notes()
        notes[0]["created_at"] = (datetime.now().astimezone() - timedelta(days=10)).isoformat()
        _save_notes(notes)

        result = await quick_note_list()
        assert "Fresh note" not in result
        assert "No pending quick notes" in result


class TestQuickNoteDone:
    async def test_marks_note_done_by_number(self):
        from app.tools.quick_notes import quick_note_create, quick_note_done, quick_note_list

        await quick_note_create("Buy eggs")
        result = await quick_note_done("1")
        assert "Marked done" in result
        assert "Buy eggs" in result
        list_result = await quick_note_list()
        assert "No pending quick notes" in list_result

    async def test_marks_note_done_by_text(self):
        from app.tools.quick_notes import quick_note_create, quick_note_done, quick_note_list

        await quick_note_create("Call mom")
        result = await quick_note_done("call mom")
        assert "Marked done" in result
        list_result = await quick_note_list()
        assert "Call mom" not in list_result

    async def test_not_found(self):
        from app.tools.quick_notes import quick_note_done

        result = await quick_note_done("nonexistent note")
        assert "Could not find" in result



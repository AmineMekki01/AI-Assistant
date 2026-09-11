"""Quick-capture voice memos - lightweight, fast note storage.

Notes are stored in a local JSON file for speed and simplicity.
They auto-expire after 7 days unless marked done.
Surfaced automatically in the daily briefing.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from ..runtime import tool


_NOTES_PATH = Path.home() / ".jarvis" / "quick_notes.json"
_AUTO_EXPIRE_DAYS = 7


def _ensure_path() -> None:
    _NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_notes() -> List[Dict[str, Any]]:
    _ensure_path()
    if not _NOTES_PATH.exists():
        return []
    try:
        data = json.loads(_NOTES_PATH.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_notes(notes: List[Dict[str, Any]]) -> None:
    _ensure_path()
    _NOTES_PATH.write_text(json.dumps(notes, indent=2))


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def _is_expired(note: Dict[str, Any]) -> bool:
    created = note.get("created_at", "")
    if not created:
        return False
    try:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        return datetime.now().astimezone() - dt > timedelta(days=_AUTO_EXPIRE_DAYS)
    except Exception:
        return False


def _prune_expired(notes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [n for n in notes if not _is_expired(n) and not n.get("done", False)]


def _pending_notes() -> List[Dict[str, Any]]:
    notes = _load_notes()
    return _prune_expired(notes)


@tool(
    name="quick_note_create",
    description="Save a quick voice memo or note. These are surfaced in the daily briefing and auto-expire after 7 days.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The note text to save"},
        },
        "required": ["text"],
    },
)
async def quick_note_create(text: str) -> str:
    if not text or not text.strip():
        return "Error: note text is required."
    note = {
        "id": str(uuid.uuid4()),
        "text": text.strip(),
        "created_at": _now_iso(),
        "done": False,
    }
    notes = _load_notes()
    notes.append(note)
    _save_notes(notes)
    return f"✓ Saved quick note: {note['text']}"


@tool(
    name="quick_note_list",
    description="List pending quick notes (excluding done and expired items).",
    parameters={
        "type": "object",
        "properties": {},
    },
)
async def quick_note_list() -> str:
    notes = _pending_notes()
    if not notes:
        return "No pending quick notes."
    lines = [f"Pending quick notes ({len(notes)}):"]
    for i, note in enumerate(notes, 1):
        text = note.get("text", "")
        created = note.get("created_at", "")
        short = text[:60] + "…" if len(text) > 60 else text
        age = ""
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                days = (datetime.now().astimezone() - dt).days
                if days == 0:
                    age = "today"
                elif days == 1:
                    age = "yesterday"
                else:
                    age = f"{days} days ago"
            except Exception:
                pass
        lines.append(f"{i}. {short}{f' ({age})' if age else ''}")
    return "\n".join(lines)


@tool(
    name="quick_note_done",
    description="Mark a quick note as done by its text or number from the list.",
    parameters={
        "type": "object",
        "properties": {
            "identifier": {
                "type": "string",
                "description": "The note text, a substring of it, or the number from quick_note_list",
            },
        },
        "required": ["identifier"],
    },
)
async def quick_note_done(identifier: str) -> str:
    if not identifier or not identifier.strip():
        return "Error: identifier is required."
    notes = _load_notes()
    needle = identifier.strip().lower()

    # Try numeric index first
    try:
        idx = int(needle)
        pending = [n for n in notes if not n.get("done", False) and not _is_expired(n)]
        if 1 <= idx <= len(pending):
            target_text = pending[idx - 1].get("text", "")
            for n in notes:
                if n.get("text") == target_text:
                    n["done"] = True
                    _save_notes(notes)
                    return f"✓ Marked done: {target_text}"
    except ValueError:
        pass

    # Try text match
    for n in notes:
        if needle in n.get("text", "").lower():
            n["done"] = True
            _save_notes(notes)
            return f"✓ Marked done: {n['text']}"

    return f"Could not find a note matching '{identifier}'."

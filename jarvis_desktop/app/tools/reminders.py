"""Smart voice reminders and timer scheduler.

Stores reminders in a SQLite database and provides tools for CRUD.
A background poller in main.py checks for due reminders and alerts the user.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..runtime import tool


_DB_PATH = Path.home() / ".jarvis" / "reminders.db"


def _ensure_db() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                due_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reminded INTEGER DEFAULT 0,
                recurring TEXT DEFAULT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _conn() -> sqlite3.Connection:
    _ensure_db()
    return sqlite3.connect(str(_DB_PATH))


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _now() -> datetime:
    return datetime.now().astimezone()


def _parse_delay(delay_str: str) -> Optional[timedelta]:
    """Parse a human delay string like '20 minutes', '1 hour', '2 days'."""
    parts = (delay_str or "").lower().strip().split()
    if not parts:
        return None
    try:
        value = float(parts[0])
    except ValueError:
        return None
    unit = parts[1] if len(parts) > 1 else "minutes"
    unit = unit.rstrip("s")  # normalize plural
    mapping = {
        "minute": timedelta(minutes=value),
        "hour": timedelta(hours=value),
        "day": timedelta(days=value),
        "week": timedelta(weeks=value),
        "second": timedelta(seconds=value),
    }
    return mapping.get(unit)


def _due_notes() -> List[Dict[str, Any]]:
    """Return reminders that are due and haven't been alerted yet."""
    conn = _conn()
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM reminders WHERE due_at <= ? AND reminded = 0 ORDER BY due_at ASC",
            (_now().isoformat(),),
        )
        rows = cursor.fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def _mark_reminded(reminder_id: str) -> None:
    conn = _conn()
    try:
        conn.execute("UPDATE reminders SET reminded = 1 WHERE id = ?", (reminder_id,))
        conn.commit()
    finally:
        conn.close()


@tool(
    name="reminder_create",
    description="Create a reminder or timer. Supports relative time like 'in 20 minutes' or absolute ISO time.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "What to remind the user about"},
            "delay": {
                "type": "string",
                "description": "Relative delay, e.g. '20 minutes', '1 hour', '2 days'",
            },
            "absolute_time": {
                "type": "string",
                "description": "ISO datetime string for absolute scheduling (optional, overrides delay)",
            },
        },
        "required": ["text"],
    },
)
async def reminder_create(text: str, delay: str = "", absolute_time: str = "") -> str:
    if not text or not text.strip():
        return "Error: reminder text is required."

    now = _now()
    if absolute_time:
        try:
            due = datetime.fromisoformat(absolute_time.replace("Z", "+00:00"))
        except Exception:
            return f"Error: could not parse absolute_time '{absolute_time}'."
    elif delay:
        delta = _parse_delay(delay)
        if delta is None:
            return f"Error: could not parse delay '{delay}'. Try formats like '20 minutes', '1 hour', '2 days'."
        due = now + delta
    else:
        # Default to 15 minutes if nothing specified
        due = now + timedelta(minutes=15)

    if due <= now:
        return "Error: reminder time must be in the future."

    reminder_id = str(uuid.uuid4())
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO reminders (id, text, due_at, created_at) VALUES (?, ?, ?, ?)",
            (reminder_id, text.strip(), due.isoformat(), now.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    # Human-friendly time description
    delta = due - now
    if delta.total_seconds() < 3600:
        friendly = f"in {int(delta.total_seconds() / 60)} minutes"
    elif delta.total_seconds() < 86400:
        friendly = f"in {int(delta.total_seconds() / 3600)} hours"
    else:
        friendly = f"in {delta.days} days"

    return f"Reminder set: '{text.strip()}' {friendly}."


@tool(
    name="reminder_list",
    description="List upcoming reminders that haven't been alerted yet.",
    parameters={
        "type": "object",
        "properties": {},
    },
)
async def reminder_list() -> str:
    conn = _conn()
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM reminders WHERE reminded = 0 ORDER BY due_at ASC"
        )
        rows = cursor.fetchall()
        reminders = [_row_to_dict(r) for r in rows]
    finally:
        conn.close()

    if not reminders:
        return "No upcoming reminders."

    lines = [f"Upcoming reminders ({len(reminders)}):"]
    now = _now()
    for i, r in enumerate(reminders, 1):
        text = r["text"]
        due_str = r["due_at"]
        try:
            due = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
            delta = due - now
            if delta.total_seconds() < 0:
                time_left = "overdue"
            elif delta.total_seconds() < 60:
                time_left = "in less than a minute"
            elif delta.total_seconds() < 3600:
                time_left = f"in {int(delta.total_seconds() / 60)} minutes"
            elif delta.total_seconds() < 86400:
                time_left = f"in {int(delta.total_seconds() / 3600)} hours"
            else:
                time_left = f"in {delta.days} days"
        except Exception:
            time_left = due_str
        lines.append(f"{i}. {text} ({time_left})")
    return "\n".join(lines)


@tool(
    name="reminder_cancel",
    description="Cancel a reminder by its text or number from the list.",
    parameters={
        "type": "object",
        "properties": {
            "identifier": {
                "type": "string",
                "description": "Reminder text, substring, or number from reminder_list",
            },
        },
        "required": ["identifier"],
    },
)
async def reminder_cancel(identifier: str) -> str:
    if not identifier or not identifier.strip():
        return "Error: identifier is required."
    needle = identifier.strip().lower()

    conn = _conn()
    try:
        # Try numeric index first
        try:
            idx = int(needle)
            cursor = conn.execute(
                "SELECT id, text FROM reminders WHERE reminded = 0 ORDER BY due_at ASC"
            )
            rows = cursor.fetchall()
            if 1 <= idx <= len(rows):
                target_id = rows[idx - 1][0]
                target_text = rows[idx - 1][1]
                conn.execute("DELETE FROM reminders WHERE id = ?", (target_id,))
                conn.commit()
                return f"Cancelled reminder: {target_text}"
        except ValueError:
            pass

        # Try text match
        cursor = conn.execute(
            "SELECT id, text FROM reminders WHERE reminded = 0 AND LOWER(text) LIKE ?",
            (f"%{needle}%",),
        )
        row = cursor.fetchone()
        if row:
            conn.execute("DELETE FROM reminders WHERE id = ?", (row[0],))
            conn.commit()
            return f"Cancelled reminder: {row[1]}"

        return f"Could not find a reminder matching '{identifier}'."
    finally:
        conn.close()


@tool(
    name="reminder_snooze",
    description="Snooze a due reminder by N minutes.",
    parameters={
        "type": "object",
        "properties": {
            "identifier": {
                "type": "string",
                "description": "Reminder text or number from the list",
            },
            "minutes": {
                "type": "integer",
                "description": "Minutes to snooze (default 10)",
            },
        },
        "required": ["identifier"],
    },
)
async def reminder_snooze(identifier: str, minutes: int = 10) -> str:
    if not identifier or not identifier.strip():
        return "Error: identifier is required."
    needle = identifier.strip().lower()
    minutes = max(1, int(minutes or 10))
    new_due = _now() + timedelta(minutes=minutes)

    conn = _conn()
    try:
        # Try numeric index
        try:
            idx = int(needle)
            cursor = conn.execute(
                "SELECT id, text FROM reminders WHERE reminded = 0 ORDER BY due_at ASC"
            )
            rows = cursor.fetchall()
            if 1 <= idx <= len(rows):
                target_id = rows[idx - 1][0]
                target_text = rows[idx - 1][1]
                conn.execute(
                    "UPDATE reminders SET due_at = ?, reminded = 0 WHERE id = ?",
                    (new_due.isoformat(), target_id),
                )
                conn.commit()
                return f"Snoozed '{target_text}' for {minutes} minutes."
        except ValueError:
            pass

        # Try text match
        cursor = conn.execute(
            "SELECT id, text FROM reminders WHERE reminded = 0 AND LOWER(text) LIKE ?",
            (f"%{needle}%",),
        )
        row = cursor.fetchone()
        if row:
            conn.execute(
                "UPDATE reminders SET due_at = ?, reminded = 0 WHERE id = ?",
                (new_due.isoformat(), row[0]),
            )
            conn.commit()
            return f"Snoozed '{row[1]}' for {minutes} minutes."

        return f"Could not find a reminder matching '{identifier}'."
    finally:
        conn.close()

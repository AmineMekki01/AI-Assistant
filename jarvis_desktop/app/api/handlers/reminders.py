"""API handlers for reminders CRUD."""
import json
import sqlite3
from pathlib import Path
from aiohttp import web


_DB_PATH = Path.home() / ".jarvis" / "reminders.db"


def _conn():
    return sqlite3.connect(str(_DB_PATH))


def _row_to_dict(row):
    return {key: row[key] for key in row.keys()}


async def handle_reminders_list(request):
    try:
        conn = _conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM reminders WHERE reminded = 0 ORDER BY due_at ASC"
        )
        rows = cursor.fetchall()
        reminders = [_row_to_dict(r) for r in rows]
        conn.close()
        return web.json_response({"success": True, "reminders": reminders})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_reminders_create(request):
    try:
        data = await request.json()
        text = (data.get("text") or "").strip()
        delay = (data.get("delay") or "").strip()
        absolute_time = (data.get("absolute_time") or "").strip()

        if not text:
            return web.json_response({"success": False, "error": "text is required"}, status=400)

        import uuid
        from datetime import datetime, timedelta

        now = datetime.now().astimezone()
        if absolute_time:
            try:
                due = datetime.fromisoformat(absolute_time.replace("Z", "+00:00"))
            except Exception:
                return web.json_response({"success": False, "error": "invalid absolute_time"}, status=400)
        elif delay:
            parts = delay.lower().strip().split()
            if not parts:
                return web.json_response({"success": False, "error": "invalid delay"}, status=400)
            try:
                value = float(parts[0])
            except ValueError:
                return web.json_response({"success": False, "error": "invalid delay"}, status=400)
            unit = parts[1].rstrip("s") if len(parts) > 1 else "minute"
            mapping = {
                "minute": timedelta(minutes=value),
                "hour": timedelta(hours=value),
                "day": timedelta(days=value),
                "week": timedelta(weeks=value),
                "second": timedelta(seconds=value),
            }
            delta = mapping.get(unit)
            if delta is None:
                return web.json_response({"success": False, "error": "invalid delay unit"}, status=400)
            due = now + delta
        else:
            due = now + timedelta(minutes=15)

        if due <= now:
            return web.json_response({"success": False, "error": "reminder time must be in the future"}, status=400)

        reminder_id = str(uuid.uuid4())
        conn = _conn()
        conn.execute(
            "INSERT INTO reminders (id, text, due_at, created_at) VALUES (?, ?, ?, ?)",
            (reminder_id, text, due.isoformat(), now.isoformat()),
        )
        conn.commit()
        conn.close()

        return web.json_response({
            "success": True,
            "reminder": {
                "id": reminder_id,
                "text": text,
                "due_at": due.isoformat(),
                "created_at": now.isoformat(),
            }
        })
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_reminders_cancel(request):
    try:
        data = await request.json()
        reminder_id = data.get("id", "").strip()
        if not reminder_id:
            return web.json_response({"success": False, "error": "id is required"}, status=400)

        conn = _conn()
        cursor = conn.execute("SELECT text FROM reminders WHERE id = ?", (reminder_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return web.json_response({"success": False, "error": "reminder not found"}, status=404)

        text = row[0]
        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()
        conn.close()

        return web.json_response({"success": True, "text": text})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_reminders_snooze(request):
    try:
        data = await request.json()
        reminder_id = data.get("id", "").strip()
        minutes = int(data.get("minutes", 10))
        if not reminder_id:
            return web.json_response({"success": False, "error": "id is required"}, status=400)

        from datetime import datetime, timedelta
        new_due = datetime.now().astimezone() + timedelta(minutes=max(1, minutes))

        conn = _conn()
        cursor = conn.execute("SELECT text FROM reminders WHERE id = ?", (reminder_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return web.json_response({"success": False, "error": "reminder not found"}, status=404)

        conn.execute(
            "UPDATE reminders SET due_at = ?, reminded = 0 WHERE id = ?",
            (new_due.isoformat(), reminder_id),
        )
        conn.commit()
        conn.close()

        return web.json_response({"success": True, "new_due_at": new_due.isoformat()})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

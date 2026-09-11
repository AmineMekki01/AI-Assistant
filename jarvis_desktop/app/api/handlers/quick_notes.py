"""API handlers for quick notes CRUD."""
import json
from pathlib import Path
from aiohttp import web


_NOTES_PATH = Path.home() / ".jarvis" / "quick_notes.json"


def _load_notes():
    if not _NOTES_PATH.exists():
        return []
    try:
        data = json.loads(_NOTES_PATH.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_notes(notes):
    _NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _NOTES_PATH.write_text(json.dumps(notes, indent=2))


async def handle_quick_notes_list(request):
    try:
        notes = _load_notes()
        # Exclude done notes from the main list
        pending = [n for n in notes if not n.get("done", False)]
        return web.json_response({"success": True, "notes": pending})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_quick_notes_create(request):
    try:
        data = await request.json()
        text = (data.get("text") or "").strip()
        if not text:
            return web.json_response({"success": False, "error": "text is required"}, status=400)

        import uuid
        from datetime import datetime
        note = {
            "id": str(uuid.uuid4()),
            "text": text,
            "created_at": datetime.now().astimezone().isoformat(),
            "done": False,
        }
        notes = _load_notes()
        notes.append(note)
        _save_notes(notes)
        return web.json_response({"success": True, "note": note})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_quick_notes_done(request):
    try:
        data = await request.json()
        note_id = data.get("id", "").strip()
        if not note_id:
            return web.json_response({"success": False, "error": "id is required"}, status=400)

        notes = _load_notes()
        found = False
        for n in notes:
            if n.get("id") == note_id:
                n["done"] = True
                found = True
                break
        if not found:
            return web.json_response({"success": False, "error": "note not found"}, status=404)

        _save_notes(notes)
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_quick_notes_delete(request):
    try:
        data = await request.json()
        note_id = data.get("id", "").strip()
        if not note_id:
            return web.json_response({"success": False, "error": "id is required"}, status=400)

        notes = _load_notes()
        original_len = len(notes)
        notes = [n for n in notes if n.get("id") != note_id]
        if len(notes) == original_len:
            return web.json_response({"success": False, "error": "note not found"}, status=404)

        _save_notes(notes)
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

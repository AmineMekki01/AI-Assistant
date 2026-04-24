"""Apple Calendar (macOS) handlers."""
import asyncio
import sys
import json
from pathlib import Path
from aiohttp import web


def _applescript_probe():
    """Try to run a harmless AppleScript to verify Calendar.app access."""
    import subprocess
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Calendar" to get name of first calendar'],
            capture_output=True,
            timeout=10,
            check=True,
        )
        return True, None
    except subprocess.CalledProcessError as e:
        return False, e.stderr.decode().strip() if e.stderr else str(e)
    except Exception as e:
        return False, str(e)


def _applescript_list_calendars():
    """Return list of calendar names from Calendar.app."""
    import subprocess
    try:
        result = subprocess.run(
            ["osascript", "-e", 'tell application "Calendar" to get name of calendars'],
            capture_output=True,
            timeout=10,
            check=True,
        )
        text = result.stdout.decode().strip()
        names = [n.strip() for n in text.split(",") if n.strip()]
        return names, None
    except Exception as e:
        return [], str(e)


async def handle_apple_calendar_test(request):
    """Probe macOS Calendar.app via AppleScript and cache the result."""
    if sys.platform != "darwin":
        return web.json_response({"ok": False, "error": "Apple Calendar only available on macOS"}, status=400)

    ok, err = await asyncio.get_event_loop().run_in_executor(None, _applescript_probe)

    status_path = Path.home() / ".jarvis" / "apple_calendar_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({
        "enabled": True,
        "available": sys.platform == "darwin",
        "ok": ok,
        "lastTested": asyncio.get_event_loop().time(),
        "error": err,
    }))

    print(f"🗓️  [BACKEND] Apple Calendar probe {'✓' if ok else '✗'}")
    return web.json_response({"ok": ok, "error": err or None})


async def handle_apple_calendar_status(request):
    """Return the last-cached Apple Calendar probe result."""
    if sys.platform != "darwin":
        return web.json_response({"enabled": False, "available": False, "ok": None})

    status_path = Path.home() / ".jarvis" / "apple_calendar_status.json"

    base = {"enabled": True, "available": True, "ok": None, "lastTested": None, "error": None}

    if status_path.exists():
        try:
            data = json.loads(status_path.read_text())
            base.update(data)
        except Exception:
            pass

    return web.json_response(base)


async def handle_apple_calendar_list(request):
    """Return the list of calendar names from Calendar.app."""
    if sys.platform != "darwin":
        return web.json_response({"calendars": [], "error": "Only available on macOS"})

    names, err = await asyncio.get_event_loop().run_in_executor(None, _applescript_list_calendars)
    return web.json_response({"calendars": names, "error": err or None})

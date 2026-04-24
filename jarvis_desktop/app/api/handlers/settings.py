"""Settings persistence handlers."""
import json
from pathlib import Path
from aiohttp import web


async def handle_save_settings(request):
    """Save settings including personal info."""
    try:
        data = await request.json()
        settings_path = Path.home() / ".jarvis" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        with open(settings_path, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"💾 [BACKEND] Settings saved to {settings_path}")
        return web.json_response({"success": True})
    except Exception as e:
        print(f"X [BACKEND] Error saving settings: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_load_settings(request):
    """Load settings including personal info."""
    try:
        settings_path = Path.home() / ".jarvis" / "settings.json"

        if settings_path.exists():
            with open(settings_path) as f:
                settings = json.load(f)
            return web.json_response(settings)
        else:
            return web.json_response({})
    except Exception as e:
        print(f"X [BACKEND] Error loading settings: {e}")
        return web.json_response({"error": str(e)}, status=500)

"""Health check endpoint."""
import json
from pathlib import Path

from aiohttp import web


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            merged = default.copy()
            merged.update(data)
            return merged
    except Exception:
        pass
    return default


async def handle_health(request):
    """Health check endpoint."""
    print(f"💓 [BACKEND] Health check called from {request.remote}")
    return web.json_response({"status": "ok", "service": "jarvis-api"})


async def handle_dashboard_health(request):
    """Return a consolidated integration snapshot for the settings dashboard."""
    from ...services.google_auth import load_google_credentials, token_path
    from qdrant_client import QdrantClient

    jarvis_dir = Path.home() / ".jarvis"

    google_status = {
        "connected": False,
        "lastConnected": None,
        "tokenPresent": False,
    }
    token_file = token_path()
    if token_file.exists():
        google_status["tokenPresent"] = True
        try:
            load_google_credentials(token_file, repair=False)
            google_status["connected"] = True
        except Exception:
            google_status["connected"] = False
        try:
            google_status["lastConnected"] = token_file.stat().st_mtime
        except Exception:
            pass

    qdrant_cache = _read_json(
        jarvis_dir / "qdrant_status.json",
        {"connected": False, "collectionExists": False},
    )
    qdrant_status = {
        "connected": False,
        "collectionExists": False,
        "host": qdrant_cache.get("host"),
        "port": qdrant_cache.get("port"),
        "collectionName": qdrant_cache.get("collectionName"),
        "lastChecked": qdrant_cache.get("lastChecked"),
    }
    try:
        if qdrant_cache.get("host"):
            client = QdrantClient(
                host=qdrant_cache.get("host", "localhost"),
                port=qdrant_cache.get("port", 6333),
                api_key=qdrant_cache.get("apiKey"),
            )
            collections = client.get_collections()
            qdrant_status["connected"] = True
            qdrant_status["collectionExists"] = any(
                c.name == qdrant_cache.get("collectionName") for c in collections.collections
            )
    except Exception:
        qdrant_status["connected"] = False
        qdrant_status["collectionExists"] = False
    obsidian_status = _read_json(
        jarvis_dir / "obsidian_status.json",
        {"synced": False, "lastSync": None, "fileCount": 0},
    )
    zimbra_status = _read_json(
        jarvis_dir / "zimbra_status.json",
        {"configured": False, "ok": None},
    )
    apple_status = _read_json(
        jarvis_dir / "apple_calendar_status.json",
        {"enabled": False, "available": False, "ok": None},
    )

    music_health = {"available": False, "librarySize": 0, "cacheFresh": False}
    try:
        from ...tools import music_library

        music_health = {
            "available": True,
            "librarySize": music_library.library_size(),
            "cacheFresh": bool(getattr(music_library, "_LIBRARY", []))
            and bool(getattr(music_library, "_LIBRARY_LOADED_AT", 0.0)),
        }
    except Exception:
        pass

    return web.json_response({
        "service": "jarvis-api",
        "status": "ok",
        "google": google_status,
        "qdrant": qdrant_status,
        "obsidian": obsidian_status,
        "zimbra": zimbra_status,
        "appleCalendar": apple_status,
        "music": music_health,
    })

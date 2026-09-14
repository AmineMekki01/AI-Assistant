"""Qdrant connection probes and configuration endpoints."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import web


def probe_qdrant_status() -> dict:
    """Probe the configured database and its configured memory collection."""
    parsed = urlparse(os.getenv("QDRANT_URL", "http://localhost:6333"))
    data = {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 6333,
        "collectionName": os.getenv("QDRANT_MEMORY_COLLECTION", "long_term_memory"),
    }
    result = {"connected": False, "collectionExists": False}
    client = None
    try:
        from qdrant_client import QdrantClient

        status_path = Path.home() / ".jarvis" / "qdrant_status.json"
        if status_path.exists():
            data.update(json.loads(status_path.read_text()))
            client = QdrantClient(
                host=data["host"], port=data["port"],
                api_key=data.get("apiKey"), timeout=2,
            )
        else:
            client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"), timeout=2)
        collections = client.get_collections()
        result.update(
            connected=True,
            collectionExists=any(item.name == data["collectionName"] for item in collections.collections),
        )
    except Exception:
        pass
    finally:
        if client is not None and hasattr(client, "close"):
            client.close()
    return {**result, **{key: data.get(key) for key in ("host", "port", "collectionName", "lastChecked")}}


async def handle_qdrant_status(request, *, probe=probe_qdrant_status):
    """Report connection and collection state without exposing credentials."""
    status = await asyncio.to_thread(probe)
    return web.json_response({key: status[key] for key in ("connected", "collectionExists")})


async def handle_qdrant_test(request):
    """Test Qdrant credentials and persist the local UI connection settings."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid request"}, status=400)

    host = data.get("host", "localhost")
    port = int(data.get("port", 6333))
    collection_name = data.get("collectionName", "jarvis_knowledge")
    api_key = data.get("apiKey") or None

    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(host=host, port=port, api_key=api_key)
        client.get_collections()
        status_path = Path.home() / ".jarvis" / "qdrant_status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps({
            "host": host,
            "port": port,
            "collectionName": collection_name,
            "apiKey": api_key,
        }))
        return web.json_response({"ok": True})
    except Exception as error:
        print(f"X [BACKEND] Qdrant test failed for {host}:{port}/{collection_name}: {error}")
        return web.json_response({"ok": False, "error": str(error)}, status=500)

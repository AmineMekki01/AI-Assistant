"""iTunes / Apple Music catalog service - public search + deep-link opener.
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List

from ..core.logging import StructuredLog


log = StructuredLog(__name__)


async def search_catalog(query: str, limit: int = 1) -> List[Dict[str, Any]]:
    """Hit ``itunes.apple.com/search`` off the event loop and return the raw hits."""
    params = urllib.parse.urlencode({
        "term": query,
        "media": "music",
        "entity": "song",
        "limit": limit,
    })
    url = f"https://itunes.apple.com/search?{params}"

    def _fetch() -> List[Dict[str, Any]]:
        req = urllib.request.Request(url, headers={"User-Agent": "JARVIS/1.0"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return json.loads(resp.read().decode("utf-8")).get("results", [])

    try:
        return await asyncio.get_event_loop().run_in_executor(None, _fetch)
    except Exception as e: 
        log.warning("itunes.search_failed", query=query, error=str(e))
        return []


async def open_in_music_app(url: str) -> bool:
    """Route a ``music.apple.com`` URL into Music.app via ``open -a Music``."""

    def _run() -> int:
        import subprocess

        proc = subprocess.run(
            ["open", "-a", "Music", url],
            capture_output=True, text=True, timeout=10.0,
        )
        if proc.returncode != 0:
            log.warning(
                "music.catalog.open_failed",
                stderr=proc.stderr.strip(),
                returncode=proc.returncode,
            )
        return proc.returncode

    rc = await asyncio.get_event_loop().run_in_executor(None, _run)
    return rc == 0

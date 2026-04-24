"""Music playback action - library -> catalog tier flow.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from typing import Optional

from ..core.logging import StructuredLog
from ..runtime import action
from ..services import itunes as itunes_svc
from ..tools import music_library as lib


log = StructuredLog(__name__)


_PLAYER_STATE_SCRIPT: str = (
    'tell application "Music"\n'
    '    try\n'
    '        set s to player state as text\n'
    '        set n to name of current track\n'
    '        return s & "|" & n\n'
    '    on error\n'
    '        return "error"\n'
    '    end try\n'
    'end tell'
)


async def _run_osascript(script: str, timeout: float = 10.0) -> subprocess.CompletedProcess:
    return await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=timeout,
        ),
    )

async def _play_from_library(query: str) -> Optional[str]:
    """Fuzzy-match the cache and play by database ID. ``None`` if nothing clears
    :data:`lib.LIBRARY_AUTOPLAY_THRESHOLD`."""
    if not await lib.ensure_loaded():
        log.warning("music.library.cache_unavailable")
        return None

    matches = lib.search(query, limit=3)
    if not matches:
        log.info("music.library.no_match", query=query, library_size=lib.library_size())
        return None

    top = matches[0]
    log.info(
        "music.library.top_match",
        query=query, name=top["name"], artist=top["artist"], score=top["score"],
    )
    if top["score"] < lib.LIBRARY_AUTOPLAY_THRESHOLD:
        return None

    played = await lib.play_by_database_id(top["database_id"])
    if played is None:
        return None
    return f"Now playing: {played['name']} by {played['artist']}"

async def _wait_for_playing_track(expected_name: str, timeout_s: float = 4.0) -> Optional[str]:
    expected = expected_name.strip().lower()
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        await asyncio.sleep(0.5)
        proc = await _run_osascript(_PLAYER_STATE_SCRIPT, timeout=3.0)
        out = proc.stdout.strip()
        if "|" not in out:
            continue

        state, current_name = out.split("|", 1)
        if state.lower() != "playing":
            continue

        cur = current_name.strip().lower()
        if expected in cur or cur in expected:
            return current_name

        log.info(
            "music.catalog.wrong_track_playing",
            expected=expected_name, current=current_name,
        )
        return None

    return None


async def _play_from_catalog(query: str) -> Optional[str]:
    results = await itunes_svc.search_catalog(query, limit=1)
    if not results:
        log.info("music.catalog.no_match", query=query)
        return None

    track = results[0]
    track_name = track.get("trackName", query)
    artist = track.get("artistName", "")
    url = track.get("trackViewUrl")
    if not url:
        log.info("music.catalog.no_url", query=query, track=track_name)
        return None

    log.info("music.catalog.match", query=query, track=track_name, artist=artist, url=url)

    if not await itunes_svc.open_in_music_app(url):
        return None

    await asyncio.sleep(2.0)

    play_proc = await _run_osascript('tell application "Music" to play', timeout=5.0)
    if play_proc.returncode != 0:
        log.warning("music.catalog.play_failed", stderr=play_proc.stderr.strip())
        return None

    if await _wait_for_playing_track(track_name) is None:
        log.info("music.catalog.playback_not_confirmed", query=query, track=track_name)
        return None

    return f"Now playing from Apple Music: {track_name} by {artist}"

@action(
    name="computer_play_music",
    description=(
        "Play a song in Apple Music. The tool scores the query against the user's "
        "cached library (fuzzy) and plays the best match by database ID; if no "
        "confident library match exists it opens the song from the Apple Music "
        "catalog via a deep link. Pass the user's phrase verbatim as `query`. If "
        "you already resolved a specific track via `music_library_search`, pass its "
        "`database_id` for a guaranteed exact match. Empty `query` toggles play/pause."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Song / artist / album / playlist phrase.",
            },
            "database_id": {
                "type": "string",
                "description": (
                    "Optional. Exact Apple Music `database_id` from a prior "
                    "`music_library_search` result. When provided, plays that "
                    "track directly and ignores `query`."
                ),
            },
        },
        "required": ["query"],
    },
)
async def computer_play_music(query: str = "", database_id: Optional[str] = None) -> str:
    if database_id:
        played = await lib.play_by_database_id(database_id)
        if played is not None:
            return f"Now playing: {played['name']} by {played['artist']}"
        log.info("music.play_by_id.miss", db_id=database_id)

    if not query:
        proc = await _run_osascript('tell application "Music" to playpause')
        if proc.returncode == 0:
            return "Toggled Apple Music playback."
        return f"Error: {proc.stderr.strip() or 'Music control failed'}"

    from_lib = await _play_from_library(query)
    if from_lib is not None:
        return from_lib

    from_cat = await _play_from_catalog(query)
    if from_cat is not None:
        return from_cat

    log.info("music.not_found", query=query)
    return (
        f"Error: I couldn't find '{query}' in your Apple Music library or the Apple "
        "Music catalog."
    )

"""
Cached Apple Music library - fuzzy search + play-by-database-id.

I still need to improve this tool, it's not perfect yet. but it gets the job done for now.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import subprocess
import time
from typing import Any, Dict, List, Optional

from ..core.logging import StructuredLog
from ..runtime import tool


log = StructuredLog(__name__)

LIBRARY_AUTOPLAY_THRESHOLD: float = 0.75
_LIBRARY_TTL_SECONDS: float = 30 * 60
_US: str = "\x1f"
_FIELD_SEP: str = "===FIELD==="

_LIBRARY_FETCH_SCRIPT: str = f'''
tell application "Music"
    set tid to AppleScript's text item delimiters
    set AppleScript's text item delimiters to (ASCII character 31)

    set allIDs to (database ID of every track of library playlist 1) as text
    set allNames to (name of every track of library playlist 1) as text
    set allArtists to (artist of every track of library playlist 1) as text
    set allAlbums to (album of every track of library playlist 1) as text

    set AppleScript's text item delimiters to tid
    return allIDs & "{_FIELD_SEP}" & allNames & "{_FIELD_SEP}" & allArtists & "{_FIELD_SEP}" & allAlbums
end tell
'''

_LIBRARY: List[Dict[str, str]] = []
_LIBRARY_LOADED_AT: float = 0.0
_LIBRARY_LOCK: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _LIBRARY_LOCK
    if _LIBRARY_LOCK is None:
        _LIBRARY_LOCK = asyncio.Lock()
    return _LIBRARY_LOCK


async def _run_osascript(script: str, timeout: float = 10.0) -> subprocess.CompletedProcess:
    return await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=timeout,
        ),
    )


def _cache_is_fresh() -> bool:
    return bool(_LIBRARY) and (time.time() - _LIBRARY_LOADED_AT) < _LIBRARY_TTL_SECONDS


def _parse_payload(payload: str) -> List[Dict[str, str]]:
    fields = payload.split(_FIELD_SEP)
    if len(fields) != 4:
        log.error("music.library.parse_failed", field_count=len(fields))
        return []

    ids = fields[0].split(_US)
    names = fields[1].split(_US)
    artists = fields[2].split(_US)
    albums = fields[3].split(_US)

    tracks: List[Dict[str, str]] = []
    for i in range(min(len(ids), len(names), len(artists), len(albums))):
        tid = ids[i].strip()
        name = names[i].strip()
        if not tid or not name:
            continue
        artist = artists[i].strip()
        album = albums[i].strip()
        tracks.append({
            "id": tid,
            "name": name,
            "artist": artist,
            "album": album,
            "_search": f"{name} {artist} {album}".lower(),
        })
    return tracks


async def ensure_loaded(force: bool = False) -> bool:
    """Lazily load the Music.app library into memory. Safe concurrently."""
    global _LIBRARY, _LIBRARY_LOADED_AT

    if _cache_is_fresh() and not force:
        return True

    async with _get_lock():
        if _cache_is_fresh() and not force:
            return True

        log.info("music.library.loading")
        t0 = time.time()
        try:
            proc = await _run_osascript(_LIBRARY_FETCH_SCRIPT, timeout=60.0)
        except subprocess.TimeoutExpired:
            log.error("music.library.load_timeout")
            return bool(_LIBRARY)

        if proc.returncode != 0:
            log.error("music.library.load_failed", stderr=proc.stderr.strip()[:300])
            return bool(_LIBRARY)

        tracks = _parse_payload(proc.stdout)
        if not tracks:
            return bool(_LIBRARY)
        print(f"Tracks: {tracks}")

        _LIBRARY = tracks
        _LIBRARY_LOADED_AT = time.time()
        log.info(
            "music.library.loaded",
            tracks=len(tracks),
            seconds=round(time.time() - t0, 2),
        )
        return True


def _score_track(q: str, track: Dict[str, str]) -> float:
    name = track["name"].lower()
    artist = track["artist"].lower()
    full = f"{name} by {artist}" if artist else name

    if q == name:
        return 1.0
    
    q_words = set(q.split())
    name_words = set(name.split())
    artist_words = set(artist.split())
    
    if q_words & name_words or q_words & artist_words:
        return 0.85 + 0.15 * difflib.SequenceMatcher(None, q, full).ratio()
    
    if (
        q in name or q in full or q in track["_search"]
        or name in q or full in q
    ):
        return 0.92 + 0.08 * difflib.SequenceMatcher(None, q, full).ratio()
    
    name_score = difflib.SequenceMatcher(None, q, name).ratio()
    full_score = difflib.SequenceMatcher(None, q, full).ratio()
    artist_score = difflib.SequenceMatcher(None, q, artist).ratio()
    
    return max(name_score, full_score, artist_score)


def search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Return up to ``limit`` top matches for ``query`` against the cache."""
    q = (query or "").strip().lower()
    if not q or not _LIBRARY:
        return []

    scored = [(_score_track(q, t), t) for t in _LIBRARY]
    scored = [(s, t) for s, t in scored if s > 0.3]
    scored.sort(key=lambda x: x[0], reverse=True)

    return [
        {
            "database_id": t["id"],
            "name": t["name"],
            "artist": t["artist"],
            "album": t["album"],
            "score": round(s, 3),
        }
        for s, t in scored[:limit]
    ]


async def play_by_database_id(db_id: str) -> Optional[Dict[str, str]]:
    """Play a specific library track by database ID.

    Returns ``{"name": ..., "artist": ...}`` on success or ``None`` on any
    failure so callers can fall through.
    """
    safe_id = "".join(c for c in db_id if c.isdigit())
    if not safe_id:
        return None

    script = f'''
    tell application "Music"
        activate
        try
            set t to (first track of library playlist 1 whose database ID is {safe_id})
            play t
            return "OK|" & (name of t) & "|" & (artist of t)
        on error errMsg
            return "ERR|" & errMsg
        end try
    end tell
    '''
    proc = await _run_osascript(script, timeout=10.0)
    out = proc.stdout.strip()
    log.info("music.play_by_id.result", db_id=safe_id, out=out[:120])

    if proc.returncode == 0 and out.startswith("OK|"):
        _, name, artist = out.split("|", 2)
        return {"name": name, "artist": artist}
    return None


def library_size() -> int:
    return len(_LIBRARY)

@tool(
    name="music_library_search",
    description=(
        "Fuzzy-search the user's cached Apple Music library and return the top "
        "matches with name, artist, album, and a `database_id` you can pass to "
        "`computer_play_music`. Use this to disambiguate before playing when the "
        "user's phrasing is vague or when a previous play attempt picked the "
        "wrong track. Do NOT call it for every music request - "
        "`computer_play_music` already consults the same cache internally."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Song / artist / album phrase to search for.",
            },
            "limit": {
                "type": "integer",
                "description": "Max matches to return (1-20, default 5).",
            },
        },
        "required": ["query"],
    },
)
async def music_library_search(query: str, limit: int = 5) -> str:
    try:
        lim = int(limit or 5)
    except (TypeError, ValueError):
        lim = 5
    lim = max(1, min(lim, 20))

    if not await ensure_loaded():
        return (
            "Apple Music library isn't available (is Music.app installed and accessible?)"
        )

    payload = {
        "library_size": library_size(),
        "query": query,
        "matches": search(query, limit=lim),
    }
    return json.dumps(payload, ensure_ascii=False)

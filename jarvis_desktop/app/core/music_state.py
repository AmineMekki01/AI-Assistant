"""Shared Music.app playback state helpers.

These helpers let the native voice loop quickly check whether Apple Music is
currently playing so the microphone can stay muted while external audio is
coming out of the speakers.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Optional, Tuple


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

_CACHE_TTL_SECONDS: float = 1.0
_CACHE: Tuple[float, bool] = (0.0, False)


def _query_music_playing() -> bool:
    if os.name != "posix":
        return False

    try:
        proc = subprocess.run(
            ["osascript", "-e", _PLAYER_STATE_SCRIPT],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except Exception:
        return False

    if proc.returncode != 0:
        return False

    out = (proc.stdout or "").strip()
    if "|" not in out:
        return False

    state, _ = out.split("|", 1)
    return state.strip().lower() == "playing"


def is_music_playing(force_refresh: bool = False) -> bool:
    """Return ``True`` when Music.app is actively playing audio.

    The result is cached briefly so the native voice loop can call this often
    without hammering AppleScript every iteration.
    """
    global _CACHE

    now = time.time()
    cached_at, cached_value = _CACHE
    if not force_refresh and (now - cached_at) < _CACHE_TTL_SECONDS:
        return cached_value

    current = _query_music_playing()
    _CACHE = (now, current)
    return current

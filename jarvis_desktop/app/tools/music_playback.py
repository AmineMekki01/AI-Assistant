"""Atomic music transport control - play, pause, next, prev, stop."""

from __future__ import annotations

import asyncio
import subprocess
from typing import Dict

from ..runtime import tool


_MUSIC_CONTROL_SCRIPTS: Dict[str, str] = {
    "play": 'tell application "Music" to play',
    "pause": 'tell application "Music" to pause',
    "stop": 'tell application "Music" to stop',
    "next": 'tell application "Music" to next track',
    "previous": 'tell application "Music" to previous track',
    "playpause": 'tell application "Music" to playpause',
}


async def _run_osascript(script: str, timeout: float = 10.0) -> subprocess.CompletedProcess:
    return await asyncio.wait_for(
        asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                ["osascript", "-e", script], capture_output=True, text=True, timeout=timeout,
            ),
        ),
        timeout=timeout + 1.0,
    )


@tool(
    name="computer_music_control",
    description="Control music playback: play, pause, next track, previous track, or stop.",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["play", "pause", "next", "previous", "stop"],
                "description": "Music control action",
            },
        },
        "required": ["action"],
    },
)
async def computer_music_control(action: str = "play") -> str:
    script = _MUSIC_CONTROL_SCRIPTS.get(action)
    if script is None:
        return f"Error: unknown music action: {action}"
    proc = await _run_osascript(script)
    if proc.returncode == 0:
        return f"Music {action} executed"
    return f"Error: Music control failed: {proc.stderr.strip()}"

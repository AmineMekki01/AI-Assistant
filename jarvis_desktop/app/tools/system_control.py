"""Deterministic macOS system control - open apps, open URLs, set volume.

All three wrap ``osascript`` / ``open``. No vision, no UI automation.
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import List

from ..runtime import tool


async def _run_subprocess(args: List[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    return await asyncio.wait_for(
        asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(args, capture_output=True, text=True, timeout=timeout),
        ),
        timeout=timeout + 1.0,
    )


async def _run_osascript(script: str, timeout: float = 10.0) -> subprocess.CompletedProcess:
    return await _run_subprocess(["osascript", "-e", script], timeout=timeout)


@tool(
    name="computer_open_app",
    description="Open a macOS application by name (e.g., 'Safari', 'Music').",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Application name"},
        },
        "required": ["name"],
    },
)
async def computer_open_app(name: str) -> str:
    if not name:
        return "Error: app name required"
    proc = await _run_osascript(f'tell application "{name}" to activate')
    if proc.returncode != 0:
        await _run_subprocess(["open", "-a", name])
    return f"Opened {name}"


@tool(
    name="computer_open_url",
    description="Open a URL in the default browser.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to open"},
        },
        "required": ["url"],
    },
)
async def computer_open_url(url: str) -> str:
    if not url:
        return "Error: URL required"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    await _run_subprocess(["open", url])
    return f"Opened {url}"


@tool(
    name="computer_set_volume",
    description="Set the system volume level (0-100).",
    parameters={
        "type": "object",
        "properties": {
            "level": {
                "type": "integer",
                "description": "Volume level from 0 to 100",
            },
        },
        "required": ["level"],
    },
)
async def computer_set_volume(level: int = 50) -> str:
    clamped = max(0, min(100, int(level)))
    proc = await _run_osascript(f"set volume output volume {clamped}")
    if proc.returncode == 0:
        return f"Volume set to {clamped}%"
    return f"Error: Failed to set volume: {proc.stderr.strip()}"

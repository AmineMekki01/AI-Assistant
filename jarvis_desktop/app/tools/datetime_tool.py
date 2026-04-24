"""Clock / calendar lookups for the Realtime model."""

from __future__ import annotations

from datetime import datetime
from typing import Dict

from ..runtime import tool


@tool(
    name="get_time",
    description="Get the current local time and date.",
    parameters={"type": "object", "properties": {}, "required": []},
)
async def get_time() -> Dict[str, str]:
    now = datetime.now()
    return {
        "iso": now.isoformat(),
        "local": now.strftime("%A, %B %d %Y %I:%M %p"),
        "time": now.strftime("%I:%M %p"),
        "date": now.strftime("%A, %B %d, %Y"),
    }


@tool(
    name="get_date",
    description="Get today's date.",
    parameters={"type": "object", "properties": {}, "required": []},
)
async def get_date() -> Dict[str, str]:
    now = datetime.now()
    return {
        "date": now.strftime("%A, %B %d, %Y"),
        "iso": now.date().isoformat(),
    }

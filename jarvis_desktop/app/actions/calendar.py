"""Unified calendar action - fans Google + Apple Calendar out, previews creates."""

from __future__ import annotations

import asyncio
from typing import Any, List

from ..runtime import action
from ..services import apple_calendar as apple_svc
from ..services import gcal as gcal_svc


def _resolve_sources(requested: List[str] | None) -> List[str]:
    available: List[str] = []
    if gcal_svc.is_connected():
        available.append("google")
    if apple_svc.is_enabled():
        available.append("apple")
    if not requested:
        return available
    wanted = {s.lower() for s in requested}
    return [s for s in available if s in wanted]


def _format_multi(results: list) -> str:
    lines: List[str] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            lines.append(f"[source #{i}] error: {r}")
            continue
        label, text = r
        lines.append(f"── {label} ──")
        lines.append(text or "(no results)")
    return "\n\n".join(lines)


def _indent(text: str, spaces: int = 4) -> str:
    pad = " " * spaces
    return "\n".join(pad + line for line in (text or "").splitlines())


def _is_error_string(s: Any) -> bool:
    return isinstance(s, str) and s.startswith("Error")

@action(
    name="calendar_list",
    description=(
        "List events across the user's calendars (Google + macOS Apple Calendar). "
        "Fans out to BOTH by default and merges results sorted chronologically - prefer "
        "this over `gcal_*` / `apple_cal_*` queries. The Apple side includes iCloud, "
        "Exchange, local, shared, and subscribed calendars (e.g. Holidays, Birthdays, "
        "Fêtes) that Google doesn't see."
    ),
    parameters={
        "type": "object",
        "properties": {
            "start": {"type": "string", "description": "ISO-8601 start datetime"},
            "end": {"type": "string", "description": "ISO-8601 end datetime"},
            "max_results": {
                "type": "integer",
                "description": "Max events per source (1-50), default 10",
            },
            "sources": {
                "type": "array",
                "items": {"type": "string", "enum": ["google", "apple"]},
                "description": "Which calendar sources to query. Omit to query all enabled.",
            },
        },
        "required": [],
    },
)
async def calendar_list(
    start: str = "",
    end: str = "",
    max_results: int = 10,
    sources: List[str] | None = None,
) -> str:
    resolved = _resolve_sources(sources)
    if not resolved:
        return (
            "Error: No calendars connected. Connect Google and/or enable Apple "
            "Calendar in Settings."
        )

    mr = int(max_results or 10)

    tasks = []
    if "google" in resolved:
        async def _g():
            return "Google Calendar", await gcal_svc.gcal_list_events(
                start=start, end=end, max_results=mr, calendar_id="primary",
            )
        tasks.append(_g())
    if "apple" in resolved:
        async def _a():
            return "Apple Calendar", await apple_svc.apple_cal_list_events(
                start=start, end=end, max_results=mr,
            )
        tasks.append(_a())

    results = await asyncio.gather(*tasks, return_exceptions=True)
    return _format_multi(results)


@action(
    name="calendar_create",
    description=(
        "Create a calendar event. ALWAYS call first with `confirmed=false` (or omitted) "
        "to get a preview; read it back to the user, ask for confirmation, then call "
        "again with `confirmed=true` to actually create. Choose `source`:\"apple\" when "
        "the user names a local macOS calendar (e.g. \"Personnel\", \"Travail\"), "
        "otherwise default to Google."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "start": {"type": "string", "description": "ISO-8601 start datetime"},
            "end": {"type": "string", "description": "ISO-8601 end datetime"},
            "source": {
                "type": "string",
                "enum": ["google", "apple"],
                "description": "Which calendar backend. Defaults to google.",
            },
            "calendar": {
                "type": "string",
                "description": "Calendar name/ID. Google: 'primary' by default. Apple: exact calendar name, e.g. 'Personnel'.",
            },
            "attendees": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Attendee emails (Google only)",
            },
            "description": {"type": "string"},
            "location": {"type": "string"},
            "confirmed": {
                "type": "boolean",
                "description": "Set true ONLY after the user has verbally confirmed the event.",
            },
        },
        "required": ["title", "start", "end"],
    },
)
async def calendar_create(
    title: str,
    start: str,
    end: str,
    source: str = "google",
    calendar: str = "",
    attendees: List[str] | None = None,
    description: str = "",
    location: str = "",
    confirmed: bool = False,
    notes: str = "",
) -> str:
    title = (title or "").strip()
    source = (source or "google").lower()
    description = description or notes or ""

    if not title or not start or not end:
        return "Error: 'title', 'start' and 'end' are required"
    if source not in ("google", "apple"):
        return f"Error: Unknown source: {source}"

    if not confirmed:
        cal_desc = calendar or ("primary" if source == "google" else "first writable")
        attendee_str = ", ".join(attendees) if attendees else "none"
        return (
            f"DRAFT EVENT (not created yet - ask the user to confirm):\n"
            f"  Source:   {source}\n"
            f"  Calendar: {cal_desc}\n"
            f"  Title:    {title}\n"
            f"  Start:    {start}\n"
            f"  End:      {end}\n"
            f"  Location: {location or '-'}\n"
            f"  Attendees:{' ' + attendee_str}\n"
            f"  Notes:\n{_indent(description) if description else '    -'}\n\n"
            "Read this back to the user, ask \"Shall I add it?\", and only call "
            "calendar_create again with confirmed=true after they say yes."
        )

    if source == "google":
        return await gcal_svc.gcal_create_event(
            title=title, start=start, end=end,
            description=description, location=location,
            attendees=attendees or [],
            calendar_id=calendar or "primary",
        )
    return await apple_svc.apple_cal_create_event(
        title=title, start=start, end=end,
        calendar=calendar, notes=description, location=location,
    )

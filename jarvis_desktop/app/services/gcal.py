"""Google Calendar service - thin async wrappers around the Calendar API."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    _GOOGLE_AVAILABLE = True
except ImportError:
    _GOOGLE_AVAILABLE = False
    build = None
    HttpError = Exception

from .google_auth import load_google_credentials


SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _token_path() -> str:
    return os.path.expanduser(
        os.getenv("GOOGLE_TOKEN_PATH", "~/.jarvis/google_token.json")
    )


def _fmt_event_time(event_time: dict) -> str:
    if not event_time:
        return ""
    if "dateTime" in event_time:
        try:
            dt = datetime.fromisoformat(event_time["dateTime"].replace("Z", "+00:00"))
            return dt.strftime("%a %b %d, %Y %I:%M %p")
        except Exception:
            return event_time["dateTime"]
    if "date" in event_time:
        return f"{event_time['date']} (all-day)"
    return ""


def _ensure_iso_with_tz(value: str) -> str:
    if not value:
        return value
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _build_service_sync():
    if not _GOOGLE_AVAILABLE:
        return None, "Google client libraries not installed. Run `pip install -r requirements.txt`."

    token_path = _token_path()
    if not os.path.exists(token_path):
        return None, (
            "Google account is not connected. Open JARVIS Settings -> Integrations -> "
            "Google and click 'Connect Google Account'."
        )

    try:
        creds, repaired = load_google_credentials(token_path, repair=True)
        if repaired:
            print("🔧 Repaired Google credentials file for Calendar")
    except Exception as e:
        return None, f"Invalid Google credentials. Please reconnect the account in Settings. ({e})"

    granted = set(creds.scopes or [])
    calendar_scopes = {
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.readonly",
    }
    if not (granted & calendar_scopes):
        return None, (
            "The connected Google account has not granted Calendar access. "
            "Open JARVIS Settings -> Integrations -> Google, click 'Disconnect', "
            "then 'Connect Google Account' again to grant Calendar permission."
        )

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                from google.auth.transport.requests import Request

                creds.refresh(Request())
                os.makedirs(os.path.dirname(token_path), exist_ok=True)
                with open(token_path, "w") as f:
                    f.write(creds.to_json())
            except Exception as e: 
                return None, f"Failed to refresh Google credentials: {e}"
        else:
            return None, "Google credentials are invalid. Please reconnect the account in Settings."

    return build("calendar", "v3", credentials=creds, cache_discovery=False), ""


async def _service_or_error():
    return await asyncio.get_event_loop().run_in_executor(None, _build_service_sync)


def _run(fn):
    return asyncio.get_event_loop().run_in_executor(None, fn)

async def gcal_list_events(
    start: str = "",
    end: str = "",
    max_results: int = 10,
    calendar_id: str = "primary",
) -> str:
    service, err = await _service_or_error()
    if err:
        return f"Error: {err}"

    now = datetime.now(timezone.utc)
    time_min = _ensure_iso_with_tz(start) if start else now.isoformat()
    time_max = _ensure_iso_with_tz(end) if end else (now + timedelta(days=7)).isoformat()
    max_results = max(1, min(int(max_results or 10), 50))

    def _do() -> str:
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        items = result.get("items", [])
        if not items:
            return f"No events found on calendar '{calendar_id}' between {time_min} and {time_max}."

        lines = [f"{len(items)} event(s) on '{calendar_id}':"]
        for ev in items:
            summary = ev.get("summary", "(no title)")
            when = _fmt_event_time(ev.get("start", {}))
            end_str = _fmt_event_time(ev.get("end", {}))
            loc = ev.get("location")
            parts = [f"  • {when}"]
            if end_str and end_str != when:
                parts.append(f"-> {end_str}")
            parts.append(f"| {summary}")
            if loc:
                parts.append(f"@ {loc}")
            lines.append(" ".join(parts))
        return "\n".join(lines)

    try:
        return await _run(_do)
    except HttpError as e:
        return f"Google Calendar API error: {e}"
    except Exception as e:
        return f"Error accessing Google Calendar: {e}"


async def gcal_create_event(
    title: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    attendees: Optional[List[str]] = None,
    calendar_id: str = "primary",
) -> str:
    service, err = await _service_or_error()
    if err:
        return f"Error: {err}"

    if not title or not start or not end:
        return "Error: 'title', 'start' and 'end' are required to create an event."

    body = {
        "summary": title,
        "start": {"dateTime": _ensure_iso_with_tz(start)},
        "end": {"dateTime": _ensure_iso_with_tz(end)},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees if a]

    def _do() -> str:
        created = service.events().insert(calendarId=calendar_id, body=body).execute()
        link = created.get("htmlLink", "")
        return f"✓ Created event '{title}' on {_fmt_event_time(body['start'])}. {link}".strip()

    try:
        return await _run(_do)
    except HttpError as e:
        return f"Google Calendar API error: {e}"
    except Exception as e: 
        return f"Error creating event: {e}"


def is_connected() -> bool:
    """Cheap check for the ``calendar`` action to decide whether to fan out."""
    from pathlib import Path

    return Path(_token_path()).exists()

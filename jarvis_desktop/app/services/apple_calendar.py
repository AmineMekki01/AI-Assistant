"""Apple Calendar service - reads/writes macOS Calendar.app via AppleScript.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple


SETTINGS_PATH = Path.home() / ".jarvis" / "settings.json"


def _load_ui_settings() -> dict:
    try:
        if SETTINGS_PATH.exists():
            with open(SETTINGS_PATH) as f:
                data = json.load(f) or {}
            return data.get("appleCalendar", {}) or {}
    except Exception:
        pass
    return {}


def is_enabled() -> bool:
    """User has opted in via the Settings UI."""
    return bool(_load_ui_settings().get("enabled", False))


def _default_calendar() -> str:
    return _load_ui_settings().get("defaultCalendar", "") or ""


def _parse_iso(value: str) -> datetime:
    if not value:
        raise ValueError("empty datetime string")
    v = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _applescript_date_block(var_name: str, dt: datetime) -> str:
    return (
        f"set {var_name} to (current date)\n"
        f"set year of {var_name} to {dt.year}\n"
        f"set month of {var_name} to {dt.month}\n"
        f"set day of {var_name} to {dt.day}\n"
        f"set hours of {var_name} to {dt.hour}\n"
        f"set minutes of {var_name} to {dt.minute}\n"
        f"set seconds of {var_name} to {dt.second}\n"
    )


def _escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def _permission_error(stderr: str) -> bool:
    low = (stderr or "").lower()
    return (
        "not authorized" in low
        or "not allowed" in low
        or "-1743" in low
        or ("errae" in low and "permitted" in low)
    )


def _permission_hint() -> str:
    return (
        "Calendar access was denied by macOS. Open System Settings -> Privacy & Security "
        "-> Calendars, and enable access for the app running JARVIS (Terminal / VS Code / "
        "iTerm / the JARVIS app). Then try again."
    )


def _osascript_sync(script: str, timeout: int = 20) -> Tuple[bool, str, str]:
    if sys.platform != "darwin":
        return False, "", "Apple Calendar is only available on macOS."
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return False, "", "`osascript` not found. Apple Calendar requires macOS."
    except subprocess.TimeoutExpired:
        return False, "", "Apple Calendar request timed out."
    if proc.returncode != 0:
        return False, proc.stdout or "", proc.stderr.strip() or "AppleScript failed."
    return True, proc.stdout or "", ""


async def _run_osascript(script: str, timeout: int = 20) -> Tuple[bool, str, str]:
    return await asyncio.get_event_loop().run_in_executor(
        None, _osascript_sync, script, timeout,
    )


def _preflight() -> str:
    if sys.platform != "darwin":
        return "Error: Apple Calendar is only available on macOS."
    if not is_enabled():
        return (
            "Error: Apple Calendar integration is disabled. Open Settings -> Integrations "
            "-> Apple Calendar and toggle it on."
        )
    return ""

async def apple_cal_list_calendars() -> str:
    err = _preflight()
    if err:
        return err
    script = 'tell application "Calendar" to return name of every calendar'
    ok, out, err_msg = await _run_osascript(script, timeout=10)
    if not ok:
        if _permission_error(err_msg):
            return f"Error: {_permission_hint()}"
        return f"Error listing calendars: {err_msg}"
    names = [n.strip() for n in out.strip().split(",") if n.strip()]
    if not names:
        return "No calendars found in Calendar.app."
    return "Available calendars:\n" + "\n".join(f"  • {n}" for n in names)


async def apple_cal_list_events(
    start: str = "",
    end: str = "",
    max_results: int = 10,
    calendar: str = "",
) -> str:
    err = _preflight()
    if err:
        return err

    try:
        start_dt = _parse_iso(start) if start else datetime.now()
        end_dt = _parse_iso(end) if end else (start_dt + timedelta(days=7))
    except ValueError as e:
        return f"Error: invalid date format ({e}). Use ISO-8601."
    if end_dt <= start_dt:
        return "Error: 'end' must be after 'start'."

    max_results = max(1, min(int(max_results or 10), 50))

    if calendar:
        cal_filter = f'set theCalendars to (every calendar whose name is "{_escape(calendar)}")'
    else:
        cal_filter = "set theCalendars to every calendar"

    script = f"""
{_applescript_date_block("startDate", start_dt)}
{_applescript_date_block("endDate", end_dt)}
set AppleScript's text item delimiters to "|"
set outputLines to {{}}
tell application "Calendar"
    {cal_filter}
    repeat with c in theCalendars
        set calName to name of c
        try
            set evts to (every event of c whose start date is greater than or equal to startDate and start date is less than endDate)
        on error
            set evts to {{}}
        end try
        repeat with e in evts
            set evSummary to summary of e
            if evSummary is missing value then set evSummary to "(no title)"
            set evStart to (start date of e) as «class isot» as string
            set evEnd to (end date of e) as «class isot» as string
            try
                set evLoc to location of e
                if evLoc is missing value then set evLoc to ""
            on error
                set evLoc to ""
            end try
            set end of outputLines to (calName & "|" & evSummary & "|" & evStart & "|" & evEnd & "|" & evLoc)
        end repeat
    end repeat
end tell
set AppleScript's text item delimiters to linefeed
return outputLines as string
"""

    ok, out, err_msg = await _run_osascript(script, timeout=30)
    if not ok:
        if _permission_error(err_msg):
            return f"Error: {_permission_hint()}"
        return f"Error reading Apple Calendar: {err_msg}"

    rows = [r for r in out.strip().split("\n") if r.strip()]
    if not rows:
        return (
            f"No Apple Calendar events between {start_dt.isoformat(timespec='minutes')} "
            f"and {end_dt.isoformat(timespec='minutes')}."
        )

    parsed_rows = []
    for r in rows:
        parts = r.split("|", 4)
        if len(parts) < 4:
            continue
        cal, title_s, s_iso, e_iso = parts[0], parts[1], parts[2], parts[3]
        loc = parts[4] if len(parts) == 5 else ""
        try:
            s_dt = datetime.fromisoformat(s_iso)
        except Exception:
            s_dt = start_dt
        parsed_rows.append((s_dt, cal, title_s, s_iso, e_iso, loc))

    parsed_rows.sort(key=lambda x: x[0])
    parsed_rows = parsed_rows[:max_results]

    lines = [f"{len(parsed_rows)} Apple Calendar event(s):"]
    for s_dt, cal, title_s, s_iso, e_iso, loc in parsed_rows:
        try:
            s_fmt = datetime.fromisoformat(s_iso).strftime("%a %b %d, %Y %I:%M %p")
        except Exception:
            s_fmt = s_iso
        try:
            e_fmt = datetime.fromisoformat(e_iso).strftime("%I:%M %p")
        except Exception:
            e_fmt = e_iso
        extra = f" @ {loc}" if loc else ""
        lines.append(f"  • {s_fmt} -> {e_fmt} [{cal}] | {title_s}{extra}")
    return "\n".join(lines)


async def apple_cal_create_event(
    title: str,
    start: str,
    end: str,
    calendar: str = "",
    notes: str = "",
    location: str = "",
) -> str:
    err = _preflight()
    if err:
        return err

    if not title or not start or not end:
        return "Error: 'title', 'start' and 'end' are required to create an event."

    try:
        start_dt = _parse_iso(start)
        end_dt = _parse_iso(end)
    except ValueError as e:
        return f"Error: invalid date format ({e}). Use ISO-8601."
    if end_dt <= start_dt:
        return "Error: 'end' must be after 'start'."

    cal_name = calendar or _default_calendar()
    if cal_name:
        target = f'set targetCal to first calendar whose name is "{_escape(cal_name)}"'
    else:
        target = "set targetCal to first calendar whose writable is true"

    props = [
        f'summary:"{_escape(title)}"',
        "start date:startDate",
        "end date:endDate",
    ]
    if notes:
        props.append(f'description:"{_escape(notes)}"')
    if location:
        props.append(f'location:"{_escape(location)}"')

    script = f"""
{_applescript_date_block("startDate", start_dt)}
{_applescript_date_block("endDate", end_dt)}
tell application "Calendar"
    try
        {target}
    on error
        return "ERR_NO_CALENDAR"
    end try
    tell targetCal
        set newEv to make new event with properties {{{", ".join(props)}}}
        return (summary of newEv) & " | " & (name of targetCal)
    end tell
end tell
"""

    ok, out, err_msg = await _run_osascript(script, timeout=20)
    if not ok:
        if _permission_error(err_msg):
            return f"Error: {_permission_hint()}"
        return f"Error creating event: {err_msg}"
    result = out.strip()
    if result == "ERR_NO_CALENDAR":
        return (
            f"Error: calendar '{cal_name}' not found in Calendar.app. "
            "List the calendars first to see available names."
        )
    return f"✓ Created Apple Calendar event: {result}"

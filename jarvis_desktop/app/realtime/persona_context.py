"""Live context and reusable prompt fragments for the JARVIS persona."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx


def detect_integrations() -> dict[str, Any]:
    """Inspect saved local state and report which integrations are usable."""
    home = Path.home()
    settings_path = home / ".jarvis" / "settings.json"
    try:
        settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    except Exception:
        settings = {}

    zimbra = settings.get("zimbra") or {}
    apple_calendar = settings.get("appleCalendar") or {}
    obsidian_count = 0
    try:
        status_path = home / ".jarvis" / "obsidian_status.json"
        status = json.loads(status_path.read_text()) if status_path.exists() else {}
        if status.get("synced"):
            obsidian_count = int(status.get("fileCount") or 0)
    except Exception:
        pass

    return {
        "google": (home / ".jarvis" / "google_token.json").exists(),
        "zimbra": bool(zimbra.get("enabled") and zimbra.get("email") and zimbra.get("password")),
        "apple_calendar": bool(apple_calendar.get("enabled")),
        "obsidian_notes": obsidian_count,
        "default_apple_calendar": apple_calendar.get("defaultCalendar", ""),
    }


def fetch_apple_calendars() -> list[str]:
    """List macOS Calendar names without failing persona creation."""
    if sys.platform != "darwin":
        return []
    try:
        process = subprocess.run(
            ["osascript", "-e", 'tell application "Calendar" to return name of every calendar'],
            capture_output=True, text=True, timeout=6,
        )
        if process.returncode != 0:
            return []
        return [name.strip() for name in (process.stdout or "").split(",") if name.strip()]
    except Exception:
        return []


def fetch_memory_primer(limit: int = 8) -> str:
    """Return important memories for the session prompt, or an empty string."""
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    collection = os.getenv("QDRANT_MEMORY_COLLECTION", "long_term_memory")
    user_id = os.getenv("JARVIS_USER_ID", "user")
    try:
        with httpx.Client(timeout=4.0) as client:
            response = client.post(
                f"{qdrant_url}/collections/{collection}/points/scroll",
                json={
                    "limit": max(1, min(int(limit) * 4, 100)),
                    "with_payload": True,
                    "with_vector": False,
                    "filter": {"must": [{"key": "user_id", "match": {"value": user_id}}]},
                },
            )
        if response.status_code != 200:
            return ""
        points = (response.json().get("result") or {}).get("points") or []
        points.sort(
            key=lambda point: (
                (point.get("payload", {}) or {}).get("importance", 0.5),
                (point.get("payload", {}) or {}).get("updated_at", ""),
            ),
            reverse=True,
        )
        return "\n".join(
            f"- [{payload.get('category', 'other')}; importance {float(payload.get('importance', 0.5)):.2f}] {payload.get('content', '')}"
            for point in points[:limit]
            for payload in [point.get("payload", {}) or {}]
        )
    except Exception:
        return ""


def response_style_block() -> str:
    return """── Response style ────────────────────────────────────────────────
  • Answer the user's question first.
  • Avoid reintroducing yourself or repeating "Certainly, sir" unless the user has
    just made a request that needs a brief acknowledgment.
  • Prefer plain, natural English over ornate or overly ceremonial wording.
  • If the answer is simple, keep it simple. Do not pad with extra reassurance.
  • This brevity rule does NOT apply to delegated briefings or other
    explicitly requested multi-part summaries. In those cases, speak the full
    answer clearly and do not compress it into a one-line recap.
  • For delegated briefings, the briefing result is already the final answer.
    Speak it back as-is, in full, without adding a wrapper like "That’s your
    daily briefing", without summarising it, and without appending a question.
  • If the user asks for a greeting or says something like "say hi", answer with
    one short greeting sentence only. Do not add a follow-up question unless the user
    explicitly asks for conversation.
  • If the user asks "how are you" / "how are you doing" / similar status checks,
    answer with a brief status only and do not start with "good morning/afternoon/evening".
    Do not add a follow-up question.
"""


def current_context_block(date_str: str, time_str: str, timezone: str, location: str) -> str:
    return f"""── Current context ──────────────────────────────────────────────
  • Date: {date_str}
  • Time: {time_str} ({timezone})
  • Location: {location or 'unknown'}
"""


def connected_services_block(integrations: dict[str, Any], apple_calendars: list[str]) -> str:
    lines = [
        f"  • Gmail / Google Calendar: {'connected' if integrations['google'] else 'NOT connected'}",
        f"  • Zimbra / OVH mail: {'connected' if integrations['zimbra'] else 'not configured'}",
        f"  • Apple Calendar: {'enabled' if integrations['apple_calendar'] else 'disabled'}"
        + (f" (calendars: {', '.join(apple_calendars[:8])})" if apple_calendars else ""),
        f"  • Obsidian vault: {integrations['obsidian_notes']} note(s) indexed"
        if integrations["obsidian_notes"] else "  • Obsidian vault: not synced",
    ]
    return f"""── Connected services ───────────────────────────────────────────
{chr(10).join(lines)}
"""


def memory_block(memory_primer: str) -> str:
    content = memory_primer.strip() if memory_primer and memory_primer.strip() else "(none yet)"
    return f"""── What you already know about the user ─────────────────────────
{content}
"""


def transcription_prompt(user_name: str) -> str:
    """Protect the owner's name and the wake word in speech transcription."""
    cleaned_name = user_name.strip()
    if not cleaned_name or cleaned_name.lower() == "sir":
        return ""
    return (
        "Transcribe the user's speech verbatim. "
        "Preserve names and proper nouns exactly as spoken. "
        "Preserve the wake word 'Jarvis' exactly if it is spoken. "
        f"Preserve the user's name '{cleaned_name}' exactly if it is spoken. "
        "Do not substitute similar names when audio is unclear."
    )

"""Gmail service - thin async wrappers around the Gmail REST API.
"""

from __future__ import annotations

import asyncio
import base64
import os
from email.mime.text import MIMEText
from typing import List, Optional

try:
    from googleapiclient.discovery import build
    _GOOGLE_AVAILABLE = True
except ImportError:
    _GOOGLE_AVAILABLE = False
    build = None

from .google_auth import load_google_credentials


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _token_path() -> str:
    return os.path.expanduser(
        os.getenv("GOOGLE_TOKEN_PATH", "~/.jarvis/google_token.json")
    )


def _build_service_sync():
    """Build a Gmail API service object on the calling thread.

    Returns ``(service, error_message)``. Exactly one of them is non-empty.
    """
    if not _GOOGLE_AVAILABLE:
        return None, "Google client libraries not installed."

    token_path = _token_path()
    if not os.path.exists(token_path):
        return None, "Gmail is not connected. Open Settings -> Integrations -> Google."

    try:
        creds, repaired = load_google_credentials(token_path, repair=True)
        if repaired:
            print("🔧 Repaired Google credentials file for Gmail")
    except Exception as e:
        return None, f"Invalid Google credentials. Please reconnect in Settings. ({e})"

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
            return None, "Google credentials are invalid. Please reconnect in Settings."

    return build("gmail", "v1", credentials=creds, cache_discovery=False), ""


async def _service_or_error():
    """Resolve the Gmail service off the event loop."""
    return await asyncio.get_event_loop().run_in_executor(None, _build_service_sync)


def _run(fn):
    """Run a blocking Google-API call on the executor."""
    return asyncio.get_event_loop().run_in_executor(None, fn)

async def gmail_list(max_results: int = 10, only_unread: bool = False) -> str:
    service, err = await _service_or_error()
    if err:
        return f"Error: {err}"

    max_results = max(1, min(int(max_results or 10), 25))
    q = "is:unread" if only_unread else ""

    def _do() -> str:
        results = service.users().messages().list(
            userId="me", q=q, maxResults=max_results,
        ).execute()
        messages = results.get("messages", []) or []
        if not messages:
            return "No unread emails." if only_unread else "Gmail inbox is empty for this query."

        label = "unread email(s)" if only_unread else "recent email(s)"
        lines = [f"📧 {len(messages)} {label}:"]
        for msg in messages:
            data = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
            ).execute()
            headers = {h["name"]: h["value"] for h in data["payload"]["headers"]}
            lines.append(
                f"  • {headers.get('Date', '')} | From: {headers.get('From', 'Unknown')} "
                f"| Subject: {headers.get('Subject', 'No subject')}"
            )
        return "\n".join(lines)

    try:
        return await _run(_do)
    except Exception as e: 
        return f"Error accessing Gmail: {e}"


async def gmail_search(query: str, max_results: int = 10) -> str:
    service, err = await _service_or_error()
    if err:
        return f"Error: {err}"

    max_results = max(1, min(int(max_results or 10), 25))

    def _do() -> str:
        results = service.users().messages().list(
            userId="me", q=query, maxResults=max_results,
        ).execute()
        messages = results.get("messages", []) or []
        if not messages:
            return f"No emails found for query: {query}"

        lines = [f"📧 {len(messages)} email(s) found:"]
        for msg in messages:
            data = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
            ).execute()
            headers = {h["name"]: h["value"] for h in data["payload"]["headers"]}
            lines.append(
                f"  • {headers.get('Date', '')} | From: {headers.get('From', 'Unknown')} "
                f"| {headers.get('Subject', 'No subject')}"
            )
        return "\n".join(lines)

    try:
        return await _run(_do)
    except Exception as e: 
        return f"Error searching Gmail: {e}"


async def gmail_send(to: str, subject: str, body: str) -> str:
    service, err = await _service_or_error()
    if err:
        return f"Error: {err}"

    def _do() -> str:
        message = MIMEText(body or "")
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return f"✓ Email sent to {to}"

    try:
        return await _run(_do)
    except Exception as e: 
        return f"Error sending Gmail: {e}"

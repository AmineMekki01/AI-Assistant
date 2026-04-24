"""Unified mail action - fans Gmail + Zimbra out in parallel, previews sends."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, List

from ..runtime import action
from ..services import gmail as gmail_svc
from ..services import zimbra as zimbra_svc


def _google_connected() -> bool:
    return (Path.home() / ".jarvis" / "google_token.json").exists()


def _resolve_accounts(requested: List[str] | None) -> List[str]:
    available: List[str] = []
    if _google_connected():
        available.append("gmail")
    if zimbra_svc.is_configured():
        available.append("zimbra")
    if not requested:
        return available
    wanted = {a.lower() for a in requested}
    return [a for a in available if a in wanted]


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
    name="mail_list",
    description=(
        "List recent emails across the user's mail accounts (Gmail + Zimbra/OVH), "
        "newest first. By default fans out to BOTH accounts and returns a merged "
        "list - prefer this over asking each account separately. Use the `accounts` "
        "filter only when the user explicitly names one (e.g. \"my work inbox\")."
    ),
    parameters={
        "type": "object",
        "properties": {
            "max_results": {
                "type": "integer",
                "description": "Max messages per account (1-25), default 10",
            },
            "only_unread": {
                "type": "boolean",
                "description": "If true, only unread. Default false.",
            },
            "accounts": {
                "type": "array",
                "items": {"type": "string", "enum": ["gmail", "zimbra"]},
                "description": "Which accounts to query. Omit to query all connected accounts.",
            },
        },
        "required": [],
    },
)
async def mail_list(
    max_results: int = 10,
    only_unread: bool = False,
    accounts: List[str] | None = None,
) -> str:
    resolved = _resolve_accounts(accounts)
    if not resolved:
        return "Error: No mail accounts connected. Connect Gmail and/or Zimbra in Settings."

    mr = int(max_results or 10)
    unread = bool(only_unread)

    tasks = []
    if "gmail" in resolved:
        async def _g():
            return "Gmail", await gmail_svc.gmail_list(max_results=mr, only_unread=unread)
        tasks.append(_g())
    if "zimbra" in resolved:
        async def _z():
            return "Zimbra", await zimbra_svc.zimbra_list(max_results=mr, only_unread=unread)
        tasks.append(_z())

    results = await asyncio.gather(*tasks, return_exceptions=True)
    return _format_multi(results)


@action(
    name="mail_search",
    description=(
        "Search the user's mail (Gmail + Zimbra/OVH) for a text query. "
        "Fans out to both accounts by default."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Free-text search query"},
            "max_results": {
                "type": "integer",
                "description": "Max messages per account, default 10",
            },
            "accounts": {
                "type": "array",
                "items": {"type": "string", "enum": ["gmail", "zimbra"]},
                "description": "Which accounts to query. Omit to query all connected.",
            },
        },
        "required": ["query"],
    },
)
async def mail_search(
    query: str,
    max_results: int = 10,
    accounts: List[str] | None = None,
) -> str:
    if not query:
        return "Error: 'query' is required for mail_search"
    resolved = _resolve_accounts(accounts)
    if not resolved:
        return "Error: No mail accounts connected."

    mr = int(max_results or 10)

    tasks = []
    if "gmail" in resolved:
        async def _g():
            return "Gmail", await gmail_svc.gmail_search(query=query, max_results=mr)
        tasks.append(_g())
    if "zimbra" in resolved:
        async def _z():
            return "Zimbra", await zimbra_svc.zimbra_search(query=query, max_results=mr)
        tasks.append(_z())

    results = await asyncio.gather(*tasks, return_exceptions=True)
    return _format_multi(results)


@action(
    name="mail_send",
    description=(
        "Send an email. ALWAYS call first with `confirmed=false` (or omitted) to get a "
        "preview; read the preview to the user, ask for confirmation, then call again "
        "with `confirmed=true` to actually send. Never send without an explicit user 'yes'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string"},
            "body": {"type": "string", "description": "Email body content (plain text)"},
            "account": {
                "type": "string",
                "enum": ["gmail", "zimbra"],
                "description": "Which account to send from. Defaults to gmail unless the user indicates otherwise.",
            },
            "confirmed": {
                "type": "boolean",
                "description": "Set true ONLY after the user has verbally confirmed the draft you just read back.",
            },
        },
        "required": ["to", "subject", "body"],
    },
)
async def mail_send(
    to: str,
    subject: str,
    body: str,
    account: str = "gmail",
    confirmed: bool = False,
) -> str:
    to = (to or "").strip()
    subject = (subject or "").strip()
    body = body or ""
    account = (account or "gmail").lower()

    if not to or not subject:
        return "Error: 'to' and 'subject' are required"
    if account not in ("gmail", "zimbra"):
        return f"Error: Unknown account: {account}"

    if not confirmed:
        return (
            f"DRAFT (not sent yet - ask the user to confirm):\n"
            f"  Account: {account}\n"
            f"  To:      {to}\n"
            f"  Subject: {subject}\n"
            f"  Body:\n{_indent(body)}\n\n"
            "Read this draft back to the user, ask \"Shall I send it?\", and only call "
            "mail_send again with confirmed=true after they say yes."
        )

    if account == "gmail":
        return await gmail_svc.gmail_send(to=to, subject=subject, body=body)
    return await zimbra_svc.zimbra_send(to=to, subject=subject, body=body)

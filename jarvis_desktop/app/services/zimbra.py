"""Zimbra / generic IMAP mail service.
"""

from __future__ import annotations

import asyncio
import email
import imaplib
import json
import os
import smtplib
import ssl
from email.header import decode_header
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Tuple


SETTINGS_PATH = Path.home() / ".jarvis" / "settings.json"


def _load_ui_settings() -> dict:
    try:
        if SETTINGS_PATH.exists():
            with open(SETTINGS_PATH) as f:
                data = json.load(f) or {}
            return data.get("zimbra", {}) or {}
    except Exception:
        pass
    return {}


def _resolve_config() -> Tuple[dict, bool]:
    """Return (config, enabled) preferring UI settings over env vars."""
    ui = _load_ui_settings()
    ui_has_creds = bool(ui.get("email") and ui.get("password"))

    cfg = {
        "email": ui.get("email") or os.getenv("ZIMBRA_EMAIL", ""),
        "password": ui.get("password") or os.getenv("ZIMBRA_PASSWORD", ""),
        "imap_host": ui.get("imapHost") or os.getenv("ZIMBRA_IMAP_HOST", ""),
        "imap_port": int(ui.get("imapPort") or os.getenv("ZIMBRA_IMAP_PORT", "993")),
        "smtp_host": ui.get("smtpHost") or os.getenv("ZIMBRA_SMTP_HOST", ""),
        "smtp_port": int(ui.get("smtpPort") or os.getenv("ZIMBRA_SMTP_PORT", "465")),
        "smtp_use_ssl": (
            bool(ui.get("smtpSsl")) if "smtpSsl" in ui
            else os.getenv("ZIMBRA_SMTP_SSL", "true").lower() == "true"
        ),
    }

    if ui_has_creds:
        enabled = bool(ui.get("enabled", True))
    else:
        enabled = bool(cfg["email"] and cfg["password"] and cfg["imap_host"])

    return cfg, enabled


def _decode_header_value(value: str) -> str:
    if not value:
        return ""
    try:
        parts = decode_header(value)
        out = ""
        for text, charset in parts:
            if isinstance(text, bytes):
                out += text.decode(charset or "utf-8", errors="replace")
            else:
                out += text
        return out.strip()
    except Exception:
        return str(value)


def _missing_config_message(cfg: dict, enabled: bool) -> str:
    if not enabled and (cfg["email"] or cfg["password"]):
        return (
            "Secondary mailbox is configured but disabled. "
            "Open Settings -> Integrations -> Secondary Mailbox and enable it."
        )
    return (
        "Secondary (Zimbra/IMAP) mailbox is not configured. "
        "Open Settings -> Integrations -> Secondary Mailbox and fill in the "
        "email, password, and IMAP/SMTP hosts, then click 'Test & Save Connection'."
    )


def _connect_imap(cfg: dict) -> imaplib.IMAP4_SSL:
    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"], ssl_context=ctx)
    conn.login(cfg["email"], cfg["password"])
    return conn


def _format_messages(conn, ids: List[bytes], header: str) -> str:
    lines = [header]
    for msg_id in ids:
        typ, msg_data = conn.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if typ != "OK" or not msg_data or not msg_data[0]:
            continue
        raw = msg_data[0][1]
        if not isinstance(raw, (bytes, bytearray)):
            continue
        parsed = email.message_from_bytes(raw)
        subject = _decode_header_value(parsed.get("Subject", "(no subject)"))
        sender = _decode_header_value(parsed.get("From", "(unknown)"))
        date = parsed.get("Date", "")
        lines.append(f"  • {date} | From: {sender} | {subject}")
    return "\n".join(lines)


def _list_sync(
    cfg: dict, folder: str, max_results: int, only_unread: bool,
) -> str:
    conn = _connect_imap(cfg)
    try:
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            return f"Could not open folder '{folder}'."
        criterion = "UNSEEN" if only_unread else "ALL"
        typ, data = conn.search(None, criterion)
        if typ != "OK":
            return f"IMAP search failed for {criterion} in '{folder}'."
        ids = data[0].split()
        if not ids:
            return (
                f"No unread emails in {folder}." if only_unread
                else f"Folder {folder} is empty."
            )
        ids = ids[-max_results:][::-1]
        label = "unread email(s)" if only_unread else "recent email(s)"
        return _format_messages(
            conn, ids, header=f"📧 {len(ids)} {label} in {folder}:",
        )
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _search_sync(cfg: dict, folder: str, query: str, max_results: int) -> str:
    conn = _connect_imap(cfg)
    try:
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            return f"Could not open folder '{folder}'."
        typ, data = conn.search(None, "TEXT", f'"{query}"')
        if typ != "OK":
            return f"IMAP search failed in '{folder}'."
        ids = data[0].split()
        if not ids:
            return f'No emails matching "{query}" in {folder}.'
        ids = ids[-max_results:][::-1]
        return _format_messages(
            conn, ids, header=f'📧 {len(ids)} email(s) matching "{query}" in {folder}:',
        )
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _send_sync(cfg: dict, to: str, subject: str, body: str) -> str:
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = cfg["email"]
    msg["To"] = to
    msg["Subject"] = subject

    ctx = ssl.create_default_context()
    if cfg["smtp_use_ssl"]:
        server = smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"], context=ctx)
    else:
        server = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"])
        server.starttls(context=ctx)
    try:
        server.login(cfg["email"], cfg["password"])
        server.sendmail(cfg["email"], [to], msg.as_string())
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return f"✓ Email sent to {to} via {cfg['smtp_host']}."


def _run(fn, *args):
    return asyncio.get_event_loop().run_in_executor(None, fn, *args)

async def zimbra_list(
    max_results: int = 10, only_unread: bool = False, folder: str = "INBOX",
) -> str:
    cfg, enabled = _resolve_config()
    if not enabled:
        return f"Error: {_missing_config_message(cfg, enabled)}"
    max_results = max(1, min(int(max_results or 10), 25))

    try:
        return await _run(
            _list_sync, cfg, folder or "INBOX", max_results, bool(only_unread),
        )
    except imaplib.IMAP4.error as e:
        return f"IMAP error: {e}"
    except (ssl.SSLError, OSError) as e:
        return f"Network error contacting mail server: {e}"
    except Exception as e: 
        return f"Mail error: {e}"


async def zimbra_search(query: str, max_results: int = 10, folder: str = "INBOX") -> str:
    cfg, enabled = _resolve_config()
    if not enabled:
        return f"Error: {_missing_config_message(cfg, enabled)}"
    if not query:
        return "Error: 'query' is required for search action."
    max_results = max(1, min(int(max_results or 10), 25))

    try:
        return await _run(_search_sync, cfg, folder or "INBOX", query, max_results)
    except imaplib.IMAP4.error as e:
        return f"IMAP error: {e}"
    except (ssl.SSLError, OSError) as e:
        return f"Network error contacting mail server: {e}"
    except Exception as e: 
        return f"Mail error: {e}"


async def zimbra_send(to: str, subject: str, body: str) -> str:
    cfg, enabled = _resolve_config()
    if not enabled:
        return f"Error: {_missing_config_message(cfg, enabled)}"

    try:
        return await _run(_send_sync, cfg, to, subject, body or "")
    except smtplib.SMTPException as e:
        return f"SMTP error: {e}"
    except (ssl.SSLError, OSError) as e:
        return f"Network error contacting mail server: {e}"
    except Exception as e: 
        return f"Mail error: {e}"


def is_configured() -> bool:
    """Quick check used by actions to decide whether to fan out to Zimbra."""
    _, enabled = _resolve_config()
    return enabled

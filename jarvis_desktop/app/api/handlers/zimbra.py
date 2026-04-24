"""Zimbra/IMAP mail handlers."""
import asyncio
import imaplib
import ssl
from pathlib import Path
import json
from aiohttp import web


async def handle_zimbra_test(request):
    """Test Zimbra/IMAP login with the submitted credentials and cache the result."""
    try:
        data = await request.json()
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Invalid request body: {e}"}, status=400)

    email_addr = (data.get("email") or "").strip()
    password = data.get("password") or ""
    imap_host = (data.get("imapHost") or "").strip()
    imap_port = int(data.get("imapPort") or 993)
    smtp_host = (data.get("smtpHost") or "").strip()
    smtp_port = int(data.get("smtpPort") or 465)
    smtp_ssl = bool(data.get("smtpSsl", True))

    if not email_addr or not password or not imap_host:
        return web.json_response({"ok": False, "error": "Missing email, password, or IMAP host"}, status=400)

    ok = False
    err = None
    try:
        def _test():
            ctx = ssl.create_default_context()
            with imaplib.IMAP4_SSL(imap_host, imap_port, ssl_context=ctx) as server:
                server.login(email_addr, password)
                server.select("INBOX")
                return True

        ok = await asyncio.get_event_loop().run_in_executor(None, _test)
    except Exception as e:
        err = str(e)
        ok = False

    status_path = Path.home() / ".jarvis" / "zimbra_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({
        "configured": True,
        "ok": ok,
        "lastTested": asyncio.get_event_loop().time(),
        "email": email_addr,
        "imapHost": imap_host,
        "imapPort": imap_port,
        "smtpHost": smtp_host,
        "smtpPort": smtp_port,
        "smtpSsl": smtp_ssl,
    }))

    print(f"📬 [BACKEND] Zimbra test {'✓' if ok else '✗'} for {email_addr}@{imap_host}:{imap_port}")
    return web.json_response({"ok": ok, "error": err or None})


async def handle_zimbra_status(request):
    """Return the last-cached Zimbra test status, or a reasonable default."""
    status_path = Path.home() / ".jarvis" / "zimbra_status.json"

    if status_path.exists():
        try:
            data = json.loads(status_path.read_text())
            return web.json_response(data)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    return web.json_response({
        "configured": False,
        "ok": None,
    })

"""Mail draft review and explicit user confirmation."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.core import music_state

if TYPE_CHECKING:
    from app.application.assistant import AssistantApplication


def is_music_playing(force_refresh: bool = False) -> bool:
    return music_state.is_music_playing(force_refresh=force_refresh)


class MailController:
    """Mail draft review and explicit user confirmation."""

    def __init__(self, app: AssistantApplication):
        self.app = app
        self.pending_mail_draft = None
        self._last_mail_draft_raw_text = ""
        self._mail_draft_pending = False

    def receive_draft(self, draft: dict):
        """Handle structured mail drafts from the realtime session."""
        self._mail_draft_pending = not draft.get('cleared', False)
        self._last_mail_draft_raw_text = draft.get('rawText', '')

        if self.app.bridge:
            self.app.bridge.send_mail_draft(draft)

    async def _send_confirmed_mail_draft(self, draft: dict):
        """Send the edited mail draft directly through the registry."""
        payload = {
            "to": (draft.get("to") or "").strip(),
            "subject": (draft.get("subject") or "").strip(),
            "body": draft.get("body") or "",
            "account": (draft.get("account") or "gmail").strip().lower(),
            "confirmed": True,
        }

        if self.app.session:
            try:
                await self.app.session.interrupt_active_response()
            except Exception as e:
                print(f"⚠️  [MAIL] Error interrupting active response: {e}")

        result = await self.app.registry.call("mail_send", payload)
        if result.get("ok"):
            print("✅ [MAIL] Draft sent successfully")
            if self.app.bridge:
                self.app.bridge.send_status("connected", "Email sent")
        else:
            error_msg = result.get("error", "Unknown mail error")
            print(f"⚠️  [MAIL] Failed to send edited draft: {error_msg}")
            if self.app.bridge:
                self.app.bridge.send_status("error", f"Email send failed: {error_msg}")

    def confirm(self, payload: dict | bool = True):
        """Confirm or cancel a pending mail draft from the UI."""
        if not self._mail_draft_pending:
            return
        if not self.app.session or not self.app.event_loop:
            print("⚠️  [MAIL] Session not ready for confirmation")
            return

        if isinstance(payload, dict):
            accepted = bool(payload.get("accepted", True))
            draft = payload.get("draft") if isinstance(payload.get("draft"), dict) else None
        else:
            accepted = bool(payload)
            draft = None

        self._mail_draft_pending = False
        if self.app.bridge:
            self.app.bridge.send_mail_draft({'cleared': True})

        if not accepted:
            self._last_mail_draft_raw_text = ""
            return

        if draft:
            future = asyncio.run_coroutine_threadsafe(
                self._send_confirmed_mail_draft(draft),
                self.app.event_loop,
            )
        else:
            future = asyncio.run_coroutine_threadsafe(
                self.app.session.send_user_text("yes"),
                self.app.event_loop,
            )

        try:
            future.result(timeout=2)
        except Exception as e:
            print(f"⚠️  [MAIL] Error sending confirmation: {e}")

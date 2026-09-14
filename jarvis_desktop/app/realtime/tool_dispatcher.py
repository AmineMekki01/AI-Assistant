"""Validate and execute Realtime function calls outside socket lifecycle code."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from ..actions.mail_draft import parse_mail_draft_preview
from ..core.logging import StructuredLog


log = StructuredLog(__name__)


class RealtimeToolDispatcher:
    """Own function-call deduplication, execution, and function outputs."""

    def __init__(
        self,
        *,
        registry,
        send_event: Callable[[dict[str, Any]], Awaitable[None]],
        request_response: Callable[[], Awaitable[None]],
        connection_generation: Callable[[], int],
        status: Callable[[str, str], None],
        mail_draft: Callable[[dict[str, Any]], None],
    ) -> None:
        self._registry = registry
        self._send_event = send_event
        self._request_response = request_response
        self._connection_generation = connection_generation
        self._status = status
        self._mail_draft = mail_draft
        self.seen_call_ids: set[str] = set()

    async def dispatch(self, call: dict[str, Any], *, continue_response: bool = True) -> None:
        """Execute one model function call and send its output to Realtime."""
        call_id = call.get("call_id", "")
        name = call.get("name", "")
        arguments = call.get("arguments", "{}")
        if call_id in self.seen_call_ids:
            return
        self.seen_call_ids.add(call_id)
        generation = self._connection_generation()
        try:
            args = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("Arguments must be an object")
        except (ValueError, TypeError):
            args = None

        status_was_changed = False
        if name == "delegate_to_briefing":
            try:
                self._status("connected", "Hang on please while i look into that for you...")
                status_was_changed = True
            except Exception as error:
                log.debug("status.emit_failed", name=name, error=str(error))

        started = asyncio.get_event_loop().time()
        try:
            if args is None:
                result: dict[str, Any] = {"ok": False, "error": "Invalid arguments; no action was executed."}
            else:
                if name == "mail_send" and args.get("confirmed"):
                    self._mail_draft({"cleared": True})
                result = await self._registry.call(name, args)
        except asyncio.TimeoutError:
            result = {"ok": False, "error": "Action timed out. Completion is unknown; do not retry automatically."}
        except Exception as error:
            result = {"ok": False, "error": str(error)}
        finally:
            elapsed = asyncio.get_event_loop().time() - started
            if status_was_changed:
                try:
                    self._status("connected", "J.A.R.V.I.S. SYSTEM ONLINE")
                except Exception as error:
                    log.debug("status.restore_failed", name=name, error=str(error))

        output = self._stringify(result.get("result")) if result.get("ok") else f"Error: {result.get('error', 'Unknown error')}"
        log.info("realtime.tool_call.done", name=name, kind=self._registry.kind_of(name) or "?", seconds=f"{elapsed:.2f}", ok=bool(result.get("ok")))

        if name == "mail_send" and result.get("ok"):
            draft = parse_mail_draft_preview(output)
            if draft:
                try:
                    self._mail_draft(draft)
                except Exception as error:
                    log.debug("mail_draft_callback_failed", error=str(error))

        if generation != self._connection_generation():
            return
        await self._send_event({"type": "conversation.item.create", "item": {
            "type": "function_call_output", "call_id": call_id, "output": output[:6000],
        }})
        if continue_response:
            await self._request_response()

    @staticmethod
    def _stringify(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else str(value)

"""Top-level orchestrator - the single reasoning core for the assistant."""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..core.logging import StructuredLog
from .registry import REGISTRY

log = StructuredLog(__name__)


_DEFAULT_EXCLUDED_TOOLS = {"delegate_to_startup_briefing"}


EventCallback = Callable[[str, Dict[str, Any]], None]


class Orchestrator:
    """Stateful, tool-using reasoning core shared across a conversation."""

    def __init__(
        self,
        *,
        tools: Optional[List[str]] = None,
        excluded_tools: Optional[set[str]] = None,
        model: Optional[str] = None,
        max_iterations: int = 6,
        max_tool_output_chars: int = 6000,
        max_history_messages: int = 24,
    ) -> None:
        self._client = None
        self._explicit_tools = tools
        self._excluded_tools = (
            set(excluded_tools) if excluded_tools is not None else set(_DEFAULT_EXCLUDED_TOOLS)
        )
        self._model = model
        self.max_iterations = max_iterations
        self.max_tool_output_chars = max_tool_output_chars
        self.max_history_messages = max_history_messages
        self._history: List[Dict[str, Any]] = []
        self._system_prompt: Optional[str] = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ public

    def reset(self) -> None:
        """Forget the running conversation (e.g. on a fresh activation)."""
        self._history = []

    async def handle(
        self,
        user_text: str,
        *,
        context: str = "",
        on_event: Optional[EventCallback] = None,
    ) -> str:
        """Plan + act on one user utterance and return the spoken reply text."""
        user_text = (user_text or "").strip()
        if not user_text:
            return ""

        async with self._lock:
            try:
                client = self._get_client()
            except Exception as e:
                log.error("orchestrator.client_init_failed", error=str(e))
                return "I can't reach my reasoning core right now."

            system_prompt = self._get_system_prompt()
            tool_schemas = self._chat_tool_schemas()

            messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
            if context:
                messages.append({"role": "system", "content": f"Context: {context}"})
            messages.extend(self._history)
            messages.append({"role": "user", "content": user_text})

            t0 = time.perf_counter()
            tools_called: List[str] = []
            log.info("orchestrator.turn.start", task_preview=_preview(user_text))

            final_text = await self._run_tool_loop(
                client, messages, tool_schemas, tools_called, on_event
            )

            duration = round(time.perf_counter() - t0, 3)
            log.info(
                "orchestrator.turn.done",
                seconds=duration,
                tools_called=tools_called,
                reply_preview=_preview(final_text),
            )

            self._remember(user_text, final_text)
            return final_text


    async def _run_tool_loop(
        self,
        client,
        messages: List[Dict[str, Any]],
        tool_schemas: List[Dict[str, Any]],
        tools_called: List[str],
        on_event: Optional[EventCallback],
    ) -> str:
        for iteration in range(self.max_iterations):
            try:
                resp = await client.chat.completions.create(
                    model=self._model or _default_model(),
                    messages=messages,
                    tools=tool_schemas or None,
                    tool_choice="auto" if tool_schemas else "none",
                )
            except Exception as e:
                log.error("orchestrator.llm_error", iteration=iteration, error=str(e))
                return "Something went wrong while I was thinking that through."

            choice = resp.choices[0].message
            tool_calls = choice.tool_calls or []

            assistant_entry: Dict[str, Any] = {
                "role": "assistant",
                "content": choice.content or "",
            }
            if tool_calls:
                assistant_entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "{}",
                        },
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_entry)

            if not tool_calls:
                return (choice.content or "").strip() or "I'm not sure how to help with that."

            tools_called.extend(tc.function.name for tc in tool_calls)
            results = await asyncio.gather(
                *(self._execute_tool_call(tc, on_event) for tc in tool_calls)
            )
            for tc, output in results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": output,
                })

        log.warning("orchestrator.iteration_limit", limit=self.max_iterations, tools_called=tools_called)
        messages.append({
            "role": "user",
            "content": (
                "Give your best spoken answer now using only what you've already "
                "learned. Do not request any more tool calls."
            ),
        })
        try:
            final = await client.chat.completions.create(
                model=self._model or _default_model(),
                messages=messages,
                tool_choice="none",
            )
            return (
                (final.choices[0].message.content or "").strip()
                or "I couldn't quite pin that down in time."
            )
        except Exception as e:
            log.error("orchestrator.final_llm_error", error=str(e))
            return "I couldn't quite pin that down in time."

    async def _execute_tool_call(self, tc, on_event: Optional[EventCallback]) -> tuple[Any, str]:
        tool_name = tc.function.name

        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}

        result = await REGISTRY.call(tool_name, args)
        if result.get("ok"):
            payload = result.get("result")
            output = (
                json.dumps(payload, ensure_ascii=False, default=str)
                if isinstance(payload, (dict, list))
                else str(payload)
            )
            if tool_name == "web_search":
                log.info("orchestrator.web_search_raw", output=output)
        else:
            output = f"Error: {result.get('error', 'unknown error')}"

        self._emit_side_effects(tool_name, args, result, output, on_event)

        if len(output) > self.max_tool_output_chars:
            output = output[: self.max_tool_output_chars] + "…(truncated)"

        return tc, output

    def _emit_side_effects(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Dict[str, Any],
        output: str,
        on_event: Optional[EventCallback],
    ) -> None:
        if on_event is None:
            return

        try:
            on_event("tool_result", {
                "name": tool_name,
                "args": args,
                "ok": bool(result.get("ok")),
                "output": output,
            })
        except Exception as e:
            log.debug("orchestrator.on_event_failed", tool=tool_name, error=str(e))

        # Surface a mail draft preview so the UI can render the editable card,
        # mirroring the behaviour the Realtime tool-call path used to provide.
        if tool_name == "mail_send" and result.get("ok"):
            draft = _try_parse_mail_draft(output)
            if draft:
                try:
                    on_event("mail_draft", draft)
                except Exception as e:
                    log.debug("orchestrator.mail_draft_emit_failed", error=str(e))

    def _remember(self, user_text: str, assistant_text: str) -> None:
        self._history.append({"role": "user", "content": user_text})
        if assistant_text:
            self._history.append({"role": "assistant", "content": assistant_text})
        if len(self._history) > self.max_history_messages:
            self._history = self._history[-self.max_history_messages :]

    def _tool_names(self) -> List[str]:
        if self._explicit_tools is not None:
            names = list(self._explicit_tools)
        else:
            names = REGISTRY.list_names()
        return [n for n in names if n not in self._excluded_tools]

    def _chat_tool_schemas(self) -> List[Dict[str, Any]]:
        """Translate registry (Realtime-shaped) schemas into Chat-Completions shape."""
        schemas: List[Dict[str, Any]] = []
        for name in self._tool_names():
            entry = REGISTRY._entries.get(name)
            if entry is None:
                continue
            schemas.append({
                "type": "function",
                "function": {
                    "name": entry.name,
                    "description": entry.description,
                    "parameters": entry.parameters,
                },
            })
        return schemas

    def _get_system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = _build_system_prompt()
        return self._system_prompt

    @classmethod
    def _get_client(cls):
        from openai import AsyncOpenAI

        return AsyncOpenAI()




def _build_system_prompt() -> str:
    """Compose the orchestrator system prompt from the shared JARVIS persona."""
    try:
        from ..core.realtime_session import get_jarvis_persona

        persona = get_jarvis_persona()
    except Exception as e:  # pragma: no cover - defensive
        log.debug("orchestrator.persona_load_failed", error=str(e))
        persona = (
            "You are J.A.R.V.I.S., a calm, articulate British AI butler. Keep "
            "spoken replies brief and direct."
        )

    orchestration_directive = """

── How you operate (CRITICAL) ──────────────────────────────────
You are the reasoning core. The user's speech is transcribed and given to you;
a separate voice layer reads your final reply aloud. Therefore:
  • Write your final reply as plain spoken prose - no markdown, no bullet
    characters, no URLs, no headings.
  • NEVER narrate that you are about to use a tool. Do not say "let me check",
    "one moment", "I'll look that up", or "retrieving the latest data". The user
    cannot see you working - if you announce a tool and then stop, you have
    failed. Call the tool immediately and silently, then answer.
  • For anything current, public, or time-sensitive (crypto/stock prices,
    weather, news, sports, exchange rates, "latest" anything), call `web_search`
    FIRST and answer from the result. Never answer such questions from memory.
  • Use the right tool for calendar, mail, music, notes, and memory exactly as
    described above, including the preview-then-confirm flow for sending mail and
    creating events.
  • Keep replies to one or two spoken sentences unless the user asks for more.
  • If a tool fails or returns nothing useful, say so honestly in one sentence.
"""
    return persona + orchestration_directive


def _try_parse_mail_draft(output: str) -> Optional[Dict[str, Any]]:
    try:
        from ..core.realtime_session import _parse_mail_draft_preview

        return _parse_mail_draft_preview(output)
    except Exception as e:  # pragma: no cover - defensive
        log.debug("orchestrator.mail_draft_parse_failed", error=str(e))
        return None


def _default_model() -> str:
    return (
        os.getenv("OPENAI_ORCHESTRATOR_MODEL")
        or os.getenv("OPENAI_AGENT_MODEL")
        or "gpt-5.4-nano"
    )


def _preview(value: Any, limit: int = 200) -> str:
    try:
        s = str(value)
    except Exception:
        s = repr(value)
    return s if len(s) <= limit else s[:limit] + "…"

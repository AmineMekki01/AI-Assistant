"""LLM sub-agent base class. No library dependencies.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, ClassVar, Dict, List, Optional

from ..core.logging import StructuredLog
from .registry import REGISTRY, RegistryEntry


log = StructuredLog(__name__)


DEFAULT_AGENT_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "task": {
            "type": "string",
            "description": (
                "The question or task to delegate, in natural language. Pass "
                "the user's phrasing verbatim when possible - the agent will "
                "do its own planning."
            ),
        },
        "context": {
            "type": "string",
            "description": (
                "Optional. Short context from the current conversation that "
                "the agent might need (user's current focus, prior turn, "
                "disambiguating hints). Keep it brief."
            ),
        },
    },
    "required": ["task"],
}


class Agent:
    """Base class for LLM-powered sub-agents.

    Subclasses set :attr:`name`, :attr:`description`, :attr:`tools`, and
    :attr:`system_prompt`, then call ``MyAgent.register()`` at module scope.
    """
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    tools: ClassVar[List[str]] = []
    system_prompt: ClassVar[str] = ""
    model: ClassVar[str] = ""
    max_iterations: ClassVar[int] = 6
    max_tool_output_chars: ClassVar[int] = 4000

    _client = None


    @classmethod
    def register(cls) -> None:
        """Register this agent with the global :data:`REGISTRY`.

        Validates that every tool in :attr:`tools` already exists. Call this
        at module scope, after the class body.
        """
        if not cls.name:
            raise ValueError(f"{cls.__name__}.name must be set")
        if not cls.description:
            raise ValueError(f"{cls.__name__}.description must be set")
        if not cls.system_prompt:
            raise ValueError(f"{cls.__name__}.system_prompt must be set")

        missing = [t for t in cls.tools if not REGISTRY.has(t)]
        if missing:
            raise ValueError(
                f"{cls.__name__} lists unknown tools: {missing}. "
                f"Available: {REGISTRY.list_names()}"
            )

        instance = cls()
        delegation_name = f"delegate_to_{cls.name}"

        async def handler(task: str, context: str = "") -> str:
            return await instance.run(task=task, context=context)

        REGISTRY.register(RegistryEntry(
            name=delegation_name,
            description=cls.description,
            parameters=DEFAULT_AGENT_PARAMETERS,
            handler=handler,
            kind="agent",
            module=cls.__module__,
        ))

    async def run(self, task: str, context: str = "") -> str:
        """Execute one agent turn - plan, act, observe, repeat, then answer."""
        task = (task or "").strip()
        if not task:
            return "Error: the agent was called with an empty task."

        try:
            client = self._get_client()
        except Exception as e:
            log.error("agent.client_init_failed", agent=self.name, error=str(e))
            return f"Error: could not initialise the agent LLM client ({e})."

        system_prompt = await self._maybe_prime_memory(task)

        tool_schemas = self._chat_tool_schemas()
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        if context:
            messages.append({
                "role": "system",
                "content": f"Context from the voice assistant: {context}",
            })
        messages.append({"role": "user", "content": task})

        t0 = time.perf_counter()
        tools_called: List[str] = []
        log.info(
            "agent.loop.start",
            agent=self.name, tools=self.tools, task_preview=_preview(task),
        )

        for iteration in range(self.max_iterations):
            try:
                resp = await client.chat.completions.create(
                    model=self.model or _default_model(),
                    messages=messages,
                    tools=tool_schemas or None,
                    tool_choice="auto" if tool_schemas else "none",
                )
            except Exception as e:
                log.error(
                    "agent.llm_error",
                    agent=self.name, iteration=iteration, error=str(e),
                )
                return f"Error: the agent LLM call failed ({e})."

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
                duration = round(time.perf_counter() - t0, 3)
                log.info(
                    "agent.loop.done",
                    agent=self.name,
                    iterations=iteration + 1,
                    seconds=duration,
                    tools_called=tools_called,
                )
                return choice.content or "(the agent produced no answer)"

            for tc in tool_calls:
                tool_name = tc.function.name
                tools_called.append(tool_name)

                if tool_name not in self.tools:
                    output = (
                        f"Error: tool '{tool_name}' is not in this agent's "
                        "allowed tool set."
                    )
                    log.warning(
                        "agent.tool_denied",
                        agent=self.name, tool=tool_name,
                    )
                else:
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
                    else:
                        output = f"Error: {result.get('error', 'unknown error')}"

                if len(output) > self.max_tool_output_chars:
                    output = output[: self.max_tool_output_chars] + "…(truncated)"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": output,
                })

        log.warning(
            "agent.iteration_limit",
            agent=self.name, limit=self.max_iterations, tools_called=tools_called,
        )
        messages.append({
            "role": "user",
            "content": (
                "You've reached the iteration limit. Give your best possible "
                "answer now using only what you've already learned. Do not "
                "request any more tool calls."
            ),
        })
        try:
            final = await client.chat.completions.create(
                model=self.model or _default_model(),
                messages=messages,
                tool_choice="none",
            )
            duration = round(time.perf_counter() - t0, 3)
            log.info(
                "agent.loop.forced_final",
                agent=self.name, seconds=duration, tools_called=tools_called,
            )
            return (
                final.choices[0].message.content
                or "The agent could not reach a conclusive answer within its iteration budget."
            )
        except Exception as e:
            log.error("agent.final_llm_error", agent=self.name, error=str(e))
            return (
                "The agent exhausted its iteration budget and failed to "
                f"produce a final answer ({e})."
            )

    async def _maybe_prime_memory(self, task: str) -> str:
        """Inject relevant memories into system prompt for self-referential tasks.

        Returns modified system prompt with memory context if applicable.
        """
        if "memory_recall" not in self.tools:
            return self.system_prompt

        try:
            from ..memory.retrieval import should_prime_memory, smart_recall, format_memories_for_context

            if not should_prime_memory(task):
                return self.system_prompt

            memories, _ = await smart_recall(task, top_k=3, include_recent=True)

            if not memories:
                return self.system_prompt

            memory_context = format_memories_for_context(memories, max_length=600)

            log.info(
                "agent.memory_primed",
                agent=self.name,
                memory_count=len(memories),
                task_preview=_preview(task),
            )

            return f"{self.system_prompt}\n\n{memory_context}"

        except Exception as e:
            log.debug("agent.memory_prime_failed", agent=self.name, error=str(e))
            return self.system_prompt

    @classmethod
    def _get_client(cls):
        if cls._client is None:
            from openai import AsyncOpenAI

            cls._client = AsyncOpenAI()
        return cls._client

    def _chat_tool_schemas(self) -> List[Dict[str, Any]]:
        """Translate Realtime-format schemas into Chat-Completions format.

        The registry stores Realtime's flat shape
        ``{type: function, name, description, parameters}``; chat completions
        wants ``{type: function, function: {name, description, parameters}}``.
        """
        result = []
        for name in self.tools:
            entry = REGISTRY._entries.get(name)
            if entry is None:
                continue
            result.append({
                "type": "function",
                "function": {
                    "name": entry.name,
                    "description": entry.description,
                    "parameters": entry.parameters,
                },
            })
        return result

def _default_model() -> str:
    return os.getenv("OPENAI_AGENT_MODEL", "gpt-5.4")


def _preview(value: Any, limit: int = 200) -> str:
    try:
        s = str(value)
    except Exception:
        s = repr(value)
    return s if len(s) <= limit else s[:limit] + "…"

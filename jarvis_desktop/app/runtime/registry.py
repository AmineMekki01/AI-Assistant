"""Capability registry - single source of truth for everything the Realtime model can call."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..core.logging import StructuredLog
from .catalog import capability_module_paths


log = StructuredLog(__name__)


Handler = Callable[..., Awaitable[Any]]


@dataclass
class RegistryEntry:
    """One capability exposed to the Realtime model."""

    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Handler
    kind: str  # "tool" | "action" | "agent"
    module: str = ""

    def as_openai_schema(self) -> Dict[str, Any]:
        """Shape expected by the Realtime API's ``session.tools``."""
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    """In-process registry of every capability the orchestrator can call."""

    def __init__(self) -> None:
        self._entries: Dict[str, RegistryEntry] = {}
        self._disabled: set[str] = set()
        self._timeout_seconds: float = 90.0

    def configure(self, *, disabled: tuple[str, ...] | list[str] = (), timeout: float | None = None) -> None:
        """Set runtime policy without changing registered capabilities."""
        self._disabled = {name.strip() for name in disabled if name.strip()}
        self._timeout_seconds = timeout if timeout and timeout > 0 else 90.0

    def register(self, entry: RegistryEntry) -> None:
        if entry.name in self._entries:
            existing = self._entries[entry.name]
            if existing.handler is entry.handler:
                return  # idempotent re-import
            raise ValueError(
                f"Duplicate capability name '{entry.name}': "
                f"already registered from {existing.module}, "
                f"now also from {entry.module}"
            )
        if not inspect.iscoroutinefunction(entry.handler):
            raise TypeError(
                f"Capability '{entry.name}' handler must be an async function"
            )
        self._entries[entry.name] = entry
        log.info("registry.registered", name=entry.name, kind=entry.kind)

    def has(self, name: str) -> bool:
        return name in self._entries

    def kind_of(self, name: str) -> Optional[str]:
        entry = self._entries.get(name)
        return entry.kind if entry else None

    def list_names(self) -> List[str]:
        return sorted(self._entries)

    def as_openai_tool_list(self) -> List[Dict[str, Any]]:
        """Schemas in a stable order (tools -> actions -> agents, then alpha)."""
        order = {"tool": 0, "action": 1, "skill": 2, "agent": 3}
        entries = sorted(
            (entry for entry in self._entries.values() if entry.name not in self._disabled),
            key=lambda e: (order.get(e.kind, 99), e.name),
        )
        return [e.as_openai_schema() for e in entries]

    def describe(self) -> List[Dict[str, Any]]:
        """Human-readable dump for logging/debugging."""
        return [
            {"name": e.name, "kind": e.kind, "module": e.module}
            for e in sorted(self._entries.values(), key=lambda x: x.name)
        ]

    async def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a registered capability by name.

        Always returns ``{"ok": bool, "result": any}`` on success or
        ``{"ok": False, "error": str}`` on failure. Exceptions are caught and
        logged rather than propagated so a buggy tool can't crash the session.
        """
        entry = self._entries.get(name)
        if entry is None:
            log.error(
                "registry.unknown_capability",
                name=name,
                available=self.list_names(),
            )
            return {
                "ok": False,
                "error": f"Unknown capability: {name}",
            }
        if name in self._disabled:
            return {"ok": False, "error": f"Capability disabled: {name}"}

        safe_args = args if isinstance(args, dict) else {}
        t0 = time.perf_counter()
        log.info(
            "registry.call.start",
            name=entry.name,
            kind=entry.kind,
            args_preview=_preview(safe_args),
        )

        try:
            result = await asyncio.wait_for(entry.handler(**safe_args), self._timeout_seconds)
        except asyncio.TimeoutError:
            log.error("registry.call.timeout", name=entry.name, timeout=self._timeout_seconds)
            return {"ok": False, "error": f"{name} timed out"}
        except TypeError as e:
            log.error("registry.call.bad_args", name=entry.name, error=str(e))
            return {"ok": False, "error": f"Invalid arguments for {name}: {e}"}
        except Exception as e:
            import traceback

            log.error(
                "registry.call.exception",
                name=entry.name,
                error=str(e),
                traceback=traceback.format_exc(),
            )
            return {"ok": False, "error": f"{name} failed: {e}"}

        duration = round(time.perf_counter() - t0, 3)
        log.info(
            "registry.call.ok",
            name=entry.name,
            kind=entry.kind,
            seconds=duration,
            result_preview=_preview(result),
        )
        return {"ok": True, "result": result}

REGISTRY = ToolRegistry()


def _decorator(kind: str):
    """Factory shared by the three public decorators."""

    def make(
        *,
        name: str,
        description: str,
        parameters: Optional[Dict[str, Any]] = None,
    ):
        if parameters is None:
            parameters = {
                "type": "object",
                "properties": {},
                "required": [],
            }

        def wrap(handler: Handler) -> Handler:
            entry = RegistryEntry(
                name=name,
                description=description,
                parameters=parameters,
                handler=handler,
                kind=kind,
                module=getattr(handler, "__module__", "<anonymous>"),
            )
            REGISTRY.register(entry)
            handler._registry_entry = entry
            return handler

        return wrap

    return make


tool = _decorator("tool")
action = _decorator("action")
agent = _decorator("agent")
skill = _decorator("skill")

_loaded_modules: set[str] = set()


def load_all_capabilities(extra_modules: tuple[str, ...] | list[str] = ()) -> ToolRegistry:
    """Import configured capability modules, triggering registration.

    Safe to call multiple times - subsequent calls are no-ops. Returns the
    global :data:`REGISTRY` for convenience so the caller can chain
    ``.as_openai_tool_list()`` etc.
    """
    for mod_path in capability_module_paths(extra_modules):
        if mod_path in _loaded_modules:
            continue
        importlib.import_module(mod_path)
        _loaded_modules.add(mod_path)

    log.info(
        "registry.loaded",
        total=len(REGISTRY.list_names()),
        entries=REGISTRY.describe(),
    )
    return REGISTRY

def _preview(value: Any, limit: int = 200) -> str:
    """Best-effort short string preview for logs."""
    try:
        if isinstance(value, (dict, list)):
            s = json.dumps(value, ensure_ascii=False, default=str)
        else:
            s = str(value)
    except Exception:
        s = repr(value)
    return s if len(s) <= limit else s[:limit] + "…"

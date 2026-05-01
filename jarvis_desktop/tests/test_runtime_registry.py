from __future__ import annotations

import pytest

from app.runtime.registry import RegistryEntry, ToolRegistry


async def _tool_ok(value: str = "ok") -> str:
    return value


async def _tool_fail() -> str:
    raise RuntimeError("boom")


def test_registry_registers_sorts_and_describes_entries():
    registry = ToolRegistry()
    registry.register(
        RegistryEntry(
            name="zeta",
            description="Zeta tool",
            parameters={"type": "object", "properties": {}},
            handler=_tool_ok,
            kind="tool",
            module="test.tools",
        )
    )
    registry.register(
        RegistryEntry(
            name="alpha_action",
            description="Alpha action",
            parameters={"type": "object", "properties": {}},
            handler=_tool_ok,
            kind="action",
            module="test.actions",
        )
    )
    registry.register(
        RegistryEntry(
            name="bravo_agent",
            description="Bravo agent",
            parameters={"type": "object", "properties": {}},
            handler=_tool_ok,
            kind="agent",
            module="test.agents",
        )
    )

    assert registry.list_names() == ["alpha_action", "bravo_agent", "zeta"]
    assert [entry["name"] for entry in registry.describe()] == ["alpha_action", "bravo_agent", "zeta"]
    assert [entry["name"] for entry in registry.as_openai_tool_list()] == [
        "zeta",
        "alpha_action",
        "bravo_agent",
    ]


@pytest.mark.asyncio
async def test_registry_call_handles_success_errors_and_unknown():
    registry = ToolRegistry()
    registry.register(
        RegistryEntry(
            name="echo",
            description="Echo",
            parameters={"type": "object", "properties": {}},
            handler=_tool_ok,
            kind="tool",
            module="test.tools",
        )
    )
    registry.register(
        RegistryEntry(
            name="explode",
            description="Explode",
            parameters={"type": "object", "properties": {}},
            handler=_tool_fail,
            kind="tool",
            module="test.tools",
        )
    )

    ok_result = await registry.call("echo", {"value": "hello"})
    unknown_result = await registry.call("missing", {})
    fail_result = await registry.call("explode", {})

    assert ok_result == {"ok": True, "result": "hello"}
    assert unknown_result["ok"] is False
    assert "Unknown capability" in unknown_result["error"]
    assert fail_result["ok"] is False
    assert "explode failed" in fail_result["error"]


def test_registry_rejects_sync_and_duplicate_handlers():
    registry = ToolRegistry()

    def sync_handler():
        return "bad"

    with pytest.raises(TypeError):
        registry.register(
            RegistryEntry(
                name="sync",
                description="Sync",
                parameters={"type": "object", "properties": {}},
                handler=sync_handler,  # type: ignore[arg-type]
                kind="tool",
                module="test.tools",
            )
        )

    registry.register(
        RegistryEntry(
            name="dup",
            description="Dup",
            parameters={"type": "object", "properties": {}},
            handler=_tool_ok,
            kind="tool",
            module="test.tools",
        )
    )
    registry.register(
        RegistryEntry(
            name="dup",
            description="Dup",
            parameters={"type": "object", "properties": {}},
            handler=_tool_ok,
            kind="tool",
            module="test.tools",
        )
    )
    assert registry.list_names() == ["dup"]

    async def another_tool():
        return "other"

    with pytest.raises(ValueError):
        registry.register(
            RegistryEntry(
                name="dup",
                description="Dup",
                parameters={"type": "object", "properties": {}},
                handler=another_tool,
                kind="tool",
                module="test.tools",
            )
        )

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.runtime import agent_base
from app.runtime.registry import RegistryEntry, ToolRegistry


async def fake_tool(*, value: str = "ok") -> str:
    return value


class DummyAgent(agent_base.Agent):
    name = "dummy"
    description = "Dummy agent"
    system_prompt = "You are a dummy agent."
    tools = ["sample_tool"]


class ToolCall:
    def __init__(self, call_id: str, name: str, arguments: str):
        self.id = call_id
        self.function = SimpleNamespace(name=name, arguments=arguments)


class FakeChatCompletions:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            message = SimpleNamespace(content="", tool_calls=[ToolCall("call-1", "sample_tool", '{"value": "hello"}')])
        else:
            message = SimpleNamespace(content="Final answer", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeChatCompletions())


def test_agent_register_adds_delegate_entry(monkeypatch):
    registry = ToolRegistry()
    registry.register(
        RegistryEntry(
            name="sample_tool",
            description="Sample tool",
            parameters={"type": "object", "properties": {}},
            handler=fake_tool,
            kind="tool",
            module="tests",
        )
    )
    monkeypatch.setattr(agent_base, "REGISTRY", registry)

    DummyAgent.register()

    assert registry.has("delegate_to_dummy")


@pytest.mark.asyncio
async def test_agent_run_empty_task_returns_error(monkeypatch):
    monkeypatch.setattr(agent_base, "REGISTRY", ToolRegistry())
    monkeypatch.setattr(DummyAgent, "_get_client", lambda self: None)

    agent = DummyAgent()
    result = await agent.run("")

    assert result == "Error: the agent was called with an empty task."


@pytest.mark.asyncio
async def test_agent_run_executes_tool_then_returns_final_answer(monkeypatch):
    registry = ToolRegistry()

    async def sample_tool(value: str = "") -> str:
        return f"tool:{value}"

    registry.register(
        RegistryEntry(
            name="sample_tool",
            description="Sample tool",
            parameters={"type": "object", "properties": {}},
            handler=sample_tool,
            kind="tool",
            module="tests",
        )
    )
    monkeypatch.setattr(agent_base, "REGISTRY", registry)
    monkeypatch.setattr(DummyAgent, "_get_client", lambda self: FakeClient())

    async def fake_prime_memory(self, task):
        return task

    monkeypatch.setattr(DummyAgent, "_maybe_prime_memory", fake_prime_memory)

    agent = DummyAgent()
    result = await agent.run("do something", context="extra context")

    assert result == "Final answer"

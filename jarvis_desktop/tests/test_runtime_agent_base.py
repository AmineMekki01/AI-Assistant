from __future__ import annotations

import asyncio
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


class ParallelFakeChatCompletions:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            message = SimpleNamespace(
                content="",
                tool_calls=[
                    ToolCall("call-1", "sample_tool_a", '{"value": "hello"}'),
                    ToolCall("call-2", "sample_tool_b", '{"value": "world"}'),
                ],
            )
        else:
            message = SimpleNamespace(content="Final answer", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class ParallelFakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=ParallelFakeChatCompletions())


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


@pytest.mark.asyncio
async def test_agent_run_executes_multiple_tool_calls_in_parallel(monkeypatch):
    registry = ToolRegistry()
    started = []
    release = asyncio.Event()

    async def sample_tool_a(value: str = "") -> str:
        started.append("sample_tool_a")
        if len(started) == 2:
            release.set()
        await release.wait()
        return f"a:{value}"

    async def sample_tool_b(value: str = "") -> str:
        started.append("sample_tool_b")
        if len(started) == 2:
            release.set()
        await release.wait()
        return f"b:{value}"

    registry.register(
        RegistryEntry(
            name="sample_tool_a",
            description="Sample tool A",
            parameters={"type": "object", "properties": {}},
            handler=sample_tool_a,
            kind="tool",
            module="tests",
        )
    )
    registry.register(
        RegistryEntry(
            name="sample_tool_b",
            description="Sample tool B",
            parameters={"type": "object", "properties": {}},
            handler=sample_tool_b,
            kind="tool",
            module="tests",
        )
    )
    monkeypatch.setattr(agent_base, "REGISTRY", registry)
    client = ParallelFakeClient()
    monkeypatch.setattr(DummyAgent, "_get_client", lambda self: client)

    async def fake_prime_memory(self, task):
        return task

    monkeypatch.setattr(DummyAgent, "_maybe_prime_memory", fake_prime_memory)

    agent = DummyAgent()
    result = await asyncio.wait_for(agent.run("do something else"), timeout=1)

    assert result == "Final answer"
    assert set(started) == {"sample_tool_a", "sample_tool_b"}

    tool_messages = [m for m in client.chat.completions.calls[0]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["call-1", "call-2"]
    assert tool_messages[0]["content"] == "a:hello"
    assert tool_messages[1]["content"] == "b:world"

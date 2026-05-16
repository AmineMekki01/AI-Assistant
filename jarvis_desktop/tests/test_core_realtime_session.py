from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core import config as config_module
from app.core import realtime_session as rs
from app.memory import extractor as extractor_module
from app.tools import memory as memory_tools


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


class FakeAsyncClient:
    last_instance = None

    def __init__(self, *args, **kwargs):
        self.calls = []
        self._response = FakeResponse(b"fake-mp3-bytes")
        FakeAsyncClient.last_instance = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self._response


class FakeProcess:
    def __init__(self):
        self.wait_called = False

    async def wait(self):
        self.wait_called = True
        return 0


class FakeSessionSocket:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


@pytest.mark.asyncio
async def test_build_session_config_uses_configured_voice(monkeypatch):
    monkeypatch.setattr(rs, "load_all_capabilities", lambda: None)
    monkeypatch.setattr(config_module, "get_settings", lambda: SimpleNamespace(
        openai_realtime_voice="alloy",
        personal_info={"name": "Amine"},
    ))

    session = rs.RealtimeSession()
    payload = session._build_session_config([])

    assert payload["type"] == "session.update"
    assert payload["session"]["voice"] == "alloy"
    assert "delegate_to_briefing" in payload["session"]["instructions"]
    assert "latest information" in payload["session"]["instructions"]
    assert "ask a clarifying question instead of delegating" in payload["session"]["instructions"]


@pytest.mark.asyncio
async def test_speak_direct_text_uses_openai_tts_voice(monkeypatch):
    monkeypatch.setattr(rs.sys, "platform", "darwin")
    monkeypatch.setattr(rs, "load_all_capabilities", lambda: None)
    monkeypatch.setattr(config_module, "get_settings", lambda: SimpleNamespace(
        openai_api_key="test-key",
        openai_realtime_voice="alloy",
    ))
    monkeypatch.setattr(rs.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(rs.shutil, "which", lambda name: "/usr/bin/afplay" if name == "afplay" else None)

    fake_process = FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        return fake_process

    monkeypatch.setattr(rs.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    transcript = []
    speaking = []
    session = rs.RealtimeSession(
        on_transcript=lambda role, text: transcript.append((role, text)),
        on_speaking=lambda flag: speaking.append(flag),
    )

    await session._speak_direct_text("Here is the briefing")

    assert transcript == [("assistant", "Here is the briefing")]
    assert speaking[0] is True
    assert speaking[-1] is False
    assert fake_process.wait_called is True
    assert FakeAsyncClient.last_instance.calls[0]["json"]["voice"] == "alloy"


@pytest.mark.asyncio
async def test_delegate_to_briefing_uses_normal_realtime_pipeline(monkeypatch):
    monkeypatch.setattr(rs, "load_all_capabilities", lambda: None)

    session = rs.RealtimeSession()
    session.ws = FakeSessionSocket()
    session._ws_alive = lambda: True

    spoke = []

    async def fail_if_direct_tts(text: str) -> None:
        spoke.append(text)

    monkeypatch.setattr(session, "_speak_direct_text", fail_if_direct_tts)

    async def fake_call(name, args):
        return {"ok": True, "result": "It’s a quiet day with no events."}

    monkeypatch.setattr(rs.REGISTRY, "call", fake_call)
    monkeypatch.setattr(rs.REGISTRY, "kind_of", lambda name: "agent")

    await session._handle_tool_call({
        "type": "response.function_call_arguments.done",
        "call_id": "call_123",
        "name": "delegate_to_briefing",
        "arguments": "{}",
    })

    payloads = [json.loads(message) for message in session.ws.sent]
    assert spoke == []
    assert payloads[0] == {
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": "call_123",
            "output": "It’s a quiet day with no events.",
        },
    }
    assert payloads[1] == {"type": "response.create"}


@pytest.mark.asyncio
async def test_extract_and_maybe_store_memory_routes_candidates(monkeypatch):
    stored = []

    async def fake_extract_memory_candidates(transcript, use_llm=False):
        if transcript == "no candidates":
            return []
        return [
            SimpleNamespace(content="User is Amine", category="identity", confidence=0.95, source="pattern"),
            SimpleNamespace(content="User likes tea", category="preference", confidence=0.88, source="pattern"),
            SimpleNamespace(content="User wants to ship tests", category="goal", confidence=0.4, source="pattern"),
        ]

    async def fake_memory_remember(content, category):
        stored.append((content, category))
        return f"✓ Remembered [{category}]: {content}"

    monkeypatch.setattr(rs, "load_all_capabilities", lambda: None)
    monkeypatch.setattr(extractor_module, "extract_memory_candidates", fake_extract_memory_candidates)
    monkeypatch.setattr(memory_tools, "memory_remember", fake_memory_remember)
    monkeypatch.setenv("MEMORY_EXTRACT_THRESHOLD", "0.85")
    monkeypatch.setenv("MEMORY_AUTO_CONFIRM_THRESHOLD", "0.9")

    session = rs.RealtimeSession()

    await session._extract_and_maybe_store_memory("no candidates")
    assert stored == []

    await session._extract_and_maybe_store_memory("I like tea")
    assert stored == [("User is Amine", "identity")]


@pytest.mark.asyncio
async def test_send_user_text_emits_user_message_and_response(monkeypatch):
    monkeypatch.setattr(rs, "load_all_capabilities", lambda: None)
    session = rs.RealtimeSession()
    session.ws = FakeSessionSocket()
    session._ws_alive = lambda: True

    await session.send_user_text("yes")

    payloads = [json.loads(message) for message in session.ws.sent]
    assert payloads[0]["type"] == "conversation.item.create"
    assert payloads[0]["item"]["role"] == "user"
    assert payloads[0]["item"]["content"][0]["text"] == "yes"
    assert payloads[1] == {"type": "response.create"}

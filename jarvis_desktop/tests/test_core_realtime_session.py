from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import config as config_module
from app.core import realtime_session as rs


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


@pytest.mark.asyncio
async def test_build_session_config_uses_configured_voice(monkeypatch):
    monkeypatch.setattr(rs, "load_all_capabilities", lambda: None)
    monkeypatch.setattr(config_module, "get_settings", lambda: SimpleNamespace(
        openai_realtime_voice="onyx",
        personal_info={"name": "Amine"},
    ))

    session = rs.RealtimeSession()
    payload = session._build_session_config([])

    assert payload["type"] == "session.update"
    assert payload["session"]["voice"] == "onyx"
    assert "delegate_to_briefing" in payload["session"]["instructions"]


@pytest.mark.asyncio
async def test_speak_direct_text_uses_openai_tts_voice(monkeypatch):
    monkeypatch.setattr(rs.sys, "platform", "darwin")
    monkeypatch.setattr(rs, "load_all_capabilities", lambda: None)
    monkeypatch.setattr(config_module, "get_settings", lambda: SimpleNamespace(
        openai_api_key="test-key",
        openai_realtime_voice="onyx",
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
    assert FakeAsyncClient.last_instance.calls[0]["json"]["voice"] == "onyx"

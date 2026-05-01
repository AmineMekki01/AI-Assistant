from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core import logging as logging_module
from app.tools import datetime_tool, music_library, music_playback, system_control, websearch


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 5, 1, 9, 30, tzinfo=tz or timezone.utc)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")

    def json(self):
        return self._payload


class FakeAsyncClient:
    last_request = None

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None):
        FakeAsyncClient.last_request = {"url": url, "json": json, "kwargs": self.kwargs}
        return FakeResponse(
            {
                "answer": "Summary text",
                "results": [
                    {
                        "title": "Example source",
                        "url": "https://example.com",
                        "content": "A" * 250,
                    }
                ],
            }
        )


class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.mark.asyncio
async def test_datetime_tools_return_fixed_time(monkeypatch):
    monkeypatch.setattr(datetime_tool, "datetime", FixedDateTime)

    time_result = await datetime_tool.get_time()
    date_result = await datetime_tool.get_date()

    assert time_result["iso"].startswith("2026-05-01T09:30:00")
    assert time_result["time"] == "09:30 AM"
    assert date_result["iso"] == "2026-05-01"


def test_structured_log_formats_messages(caplog):
    logger = logging_module.StructuredLog("tests.logging")
    with caplog.at_level("INFO"):
        logger.info("event.name", foo="bar", count=2)
        logger.error("event.fail", reason="boom")

    assert "event.name | foo=bar count=2" in caplog.text
    assert "event.fail | reason=boom" in caplog.text


@pytest.mark.asyncio
async def test_web_search_formats_answer_and_sources(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")
    monkeypatch.setattr(websearch.httpx, "AsyncClient", FakeAsyncClient)

    text = await websearch.web_search("jarvis testing", max_results=3)

    assert "Summary: Summary text" in text
    assert "Example source" in text
    assert "https://example.com" in text
    assert FakeAsyncClient.last_request["json"]["query"] == "jarvis testing"
    assert FakeAsyncClient.last_request["json"]["max_results"] == 3


@pytest.mark.asyncio
async def test_system_control_branches(monkeypatch):
    async def fake_run_osascript(script, timeout=10.0):
        if "set volume" in script:
            return FakeProc(returncode=0)
        return FakeProc(returncode=1, stderr="failed")

    fallback_calls = []

    async def fake_run_subprocess(args, timeout=10.0):
        fallback_calls.append(args)
        return FakeProc(returncode=0)

    monkeypatch.setattr(system_control, "_run_osascript", fake_run_osascript)
    monkeypatch.setattr(system_control, "_run_subprocess", fake_run_subprocess)

    assert await system_control.computer_open_app("Safari") == "Opened Safari"
    assert fallback_calls[0] == ["open", "-a", "Safari"]
    assert await system_control.computer_open_app("") == "Error: app name required"
    assert await system_control.computer_open_url("example.com") == "Opened https://example.com"
    assert await system_control.computer_open_url("") == "Error: URL required"
    assert await system_control.computer_set_volume(150) == "Volume set to 100%"


@pytest.mark.asyncio
async def test_music_playback_and_library_helpers(monkeypatch):
    async def fake_run_osascript(script, timeout=10.0):
        return FakeProc(returncode=0)

    monkeypatch.setattr(music_playback, "_run_osascript", fake_run_osascript)

    assert await music_playback.computer_music_control("play") == "Music play executed"
    assert await music_playback.computer_music_control("invalid") == "Error: unknown music action: invalid"

    async def failing_run_osascript(script, timeout=10.0):
        return FakeProc(returncode=1, stderr="music failed")

    monkeypatch.setattr(music_playback, "_run_osascript", failing_run_osascript)
    assert await music_playback.computer_music_control("pause") == "Error: Music control failed: music failed"

    parsed = music_library._parse_payload(
        "1\x1f2===FIELD===Song A\x1fSong B===FIELD===Artist A\x1fArtist B===FIELD===Album A\x1fAlbum B"
    )
    assert parsed[0]["name"] == "Song A"
    assert parsed[1]["artist"] == "Artist B"

    monkeypatch.setattr(music_library, "_LIBRARY", parsed)
    monkeypatch.setattr(music_library, "_LIBRARY_LOADED_AT", 0.0)
    assert music_library.library_size() == 2
    matches = music_library.search("song", limit=1)
    assert matches[0]["database_id"] == "1"

    async def fake_loaded(force=False):
        return True

    monkeypatch.setattr(music_library, "ensure_loaded", fake_loaded)
    async def fake_library_run_osascript(script, timeout=10.0):
        return FakeProc(returncode=0, stdout="OK|Song A|Artist A")

    monkeypatch.setattr(music_library, "_run_osascript", fake_library_run_osascript)
    played = await music_library.play_by_database_id("123")
    assert played == {"name": "Song A", "artist": "Artist A"}

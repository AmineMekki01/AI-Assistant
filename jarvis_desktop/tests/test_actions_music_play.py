from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.actions import music_play as music_action
from app.services import itunes as itunes_svc
from app.tools import music_library as lib


class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.mark.asyncio
async def test_music_play_routes_library_database_id_toggle_and_outer_error(monkeypatch):
    async def fake_ensure_loaded():
        return True

    async def fake_play_by_database_id(db_id):
        if db_id == "123":
            return {"name": "Song A", "artist": "Artist A"}
        return None

    async def fake_catalog_search(query, limit=1):
        if query == "catalog hit":
            return [
                {
                    "trackName": "Catalog Song",
                    "artistName": "Artist C",
                    "trackViewUrl": "https://music.apple.com/catalog-song",
                }
            ]
        return []

    def fake_search(query, limit=3):
        if query == "library hit":
            return [
                {
                    "database_id": "123",
                    "name": "Song A",
                    "artist": "Artist A",
                    "album": "Album A",
                    "score": 0.99,
                }
            ]
        if query == "low score":
            return [
                {
                    "database_id": "456",
                    "name": "Soft Song",
                    "artist": "Artist B",
                    "album": "Album B",
                    "score": 0.2,
                }
            ]
        if query == "stalled":
            return [
                {
                    "database_id": "789",
                    "name": "Stalled Song",
                    "artist": "Artist D",
                    "album": "Album D",
                    "score": 0.97,
                }
            ]
        return []

    monkeypatch.setattr(lib, "ensure_loaded", fake_ensure_loaded)
    monkeypatch.setattr(lib, "play_by_database_id", fake_play_by_database_id)
    monkeypatch.setattr(lib, "search", fake_search)
    monkeypatch.setattr(itunes_svc, "search_catalog", fake_catalog_search)

    async def open_in_music_app_ok(url):
        return True

    monkeypatch.setattr(itunes_svc, "open_in_music_app", open_in_music_app_ok)

    async def run_osascript_ok(script, timeout=10.0):
        return FakeProc(returncode=0)

    async def run_osascript_fail(script, timeout=10.0):
        return FakeProc(returncode=1, stderr="music failed")

    monkeypatch.setattr(music_action, "_run_osascript", run_osascript_ok)

    assert await music_action._play_from_library("library hit") == "Now playing: Song A by Artist A"
    assert await music_action._play_from_library("low score") is None
    assert await music_action._play_from_library("stalled") is None
    assert await music_action._play_from_library("missing") is None
    async def fake_ensure_unavailable():
        return False

    monkeypatch.setattr(lib, "ensure_loaded", fake_ensure_unavailable)
    assert await music_action._play_from_library("library hit") is None
    monkeypatch.setattr(lib, "ensure_loaded", fake_ensure_loaded)
    assert await music_action.computer_play_music(query="library hit") == "Now playing: Song A by Artist A"
    assert await music_action.computer_play_music(query="", database_id="123") == "Now playing: Song A by Artist A"
    assert await music_action.computer_play_music(query="missing", database_id="999") == (
        "Error: I couldn't find 'missing' in your Apple Music library or the Apple Music catalog."
    )
    assert await music_action.computer_play_music(query="") == "Toggled Apple Music playback."

    monkeypatch.setattr(music_action, "_run_osascript", run_osascript_fail)
    assert await music_action.computer_play_music(query="") == "Error: music failed"

    monkeypatch.setattr(music_action, "_run_osascript", run_osascript_ok)
    async def wait_catalog_ok(expected_name, timeout_s=4.0):
        return "Catalog Song"

    monkeypatch.setattr(music_action, "_wait_for_playing_track", wait_catalog_ok)
    assert await music_action.computer_play_music(query="catalog hit") == (
        "Now playing from Apple Music: Catalog Song by Artist C"
    )
    assert await music_action.computer_play_music(query="missing", database_id="999") == (
        "Error: I couldn't find 'missing' in your Apple Music library or the Apple Music catalog."
    )


@pytest.mark.asyncio
async def test_music_play_catalog_helper_branches(monkeypatch):
    async def no_sleep(delay):
        return None

    monkeypatch.setattr(music_action.asyncio, "sleep", no_sleep)

    async def search_empty(query, limit=1):
        return []

    async def open_ok(url):
        return True

    async def open_fail(url):
        return False

    async def run_ok(script, timeout=10.0):
        return FakeProc(returncode=0)

    async def run_fail(script, timeout=10.0):
        return FakeProc(returncode=1, stderr="play failed")

    monkeypatch.setattr(itunes_svc, "search_catalog", search_empty)
    assert await music_action._play_from_catalog("song") is None

    async def search_missing_url(query, limit=1):
        return [{"trackName": "Song A", "artistName": "Artist A"}]

    monkeypatch.setattr(itunes_svc, "search_catalog", search_missing_url)
    assert await music_action._play_from_catalog("song") is None

    async def search_with_url(query, limit=1):
        return [
            {
                "trackName": "Song A",
                "artistName": "Artist A",
                "trackViewUrl": "https://music.apple.com/song-a",
            }
        ]

    monkeypatch.setattr(itunes_svc, "search_catalog", search_with_url)
    monkeypatch.setattr(itunes_svc, "open_in_music_app", open_fail)
    assert await music_action._play_from_catalog("song") is None

    monkeypatch.setattr(itunes_svc, "open_in_music_app", open_ok)
    monkeypatch.setattr(music_action, "_run_osascript", run_fail)
    assert await music_action._play_from_catalog("song") is None

    monkeypatch.setattr(music_action, "_run_osascript", run_ok)
    async def wait_none(expected_name, timeout_s=4.0):
        return None

    monkeypatch.setattr(music_action, "_wait_for_playing_track", wait_none)
    assert await music_action._play_from_catalog("song") is None

    async def wait_ok(expected_name, timeout_s=4.0):
        return "Song A"

    monkeypatch.setattr(music_action, "_wait_for_playing_track", wait_ok)
    assert await music_action._play_from_catalog("song") == "Now playing from Apple Music: Song A by Artist A"


@pytest.mark.asyncio
async def test_wait_for_playing_track_handles_state_changes(monkeypatch):
    async def no_sleep(delay):
        return None

    monkeypatch.setattr(music_action.asyncio, "sleep", no_sleep)

    time_values = iter([0, 1, 2, 3, 4, 5])
    monkeypatch.setattr(music_action.time, "time", lambda: next(time_values))

    outputs = iter(["paused|Song A", "playing|Different Song"])

    async def run_state_script(script, timeout=3.0):
        return FakeProc(returncode=0, stdout=next(outputs))

    monkeypatch.setattr(music_action, "_run_osascript", run_state_script)
    assert await music_action._wait_for_playing_track("Song A", timeout_s=4.0) is None

    time_values = iter([0, 1, 2])
    monkeypatch.setattr(music_action.time, "time", lambda: next(time_values))
    outputs = iter(["playing|Song A"])
    monkeypatch.setattr(music_action, "_run_osascript", run_state_script)
    assert await music_action._wait_for_playing_track("Song A", timeout_s=4.0) == "Song A"

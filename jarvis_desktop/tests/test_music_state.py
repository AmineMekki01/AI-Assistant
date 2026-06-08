from __future__ import annotations

from app.core import music_state


def test_voice_followup_override_sets_and_expires(monkeypatch):
    current = {"value": 100.0}

    def fake_time():
        return current["value"]

    monkeypatch.setattr(music_state.time, "time", fake_time)

    music_state.set_voice_followup_override(duration_seconds=8.0)

    current["value"] = 100.0
    assert music_state.voice_followup_override_active() is True
    current["value"] = 107.9
    assert music_state.voice_followup_override_active() is True
    current["value"] = 108.1
    assert music_state.voice_followup_override_active() is False
    current["value"] = 110.0
    assert music_state.voice_followup_override_active() is False

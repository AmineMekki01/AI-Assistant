from __future__ import annotations

import json
from pathlib import Path

from app.core import config as config_module


def test_get_settings_reads_environment_and_caches(monkeypatch):
    monkeypatch.setattr(config_module.Settings, "openai_api_key", "test-key")
    monkeypatch.setattr(config_module.Settings, "openai_realtime_voice", "ash")
    monkeypatch.setattr(config_module.Settings, "google_client_id", "client-id")
    monkeypatch.setattr(config_module.Settings, "google_client_secret", "client-secret")
    monkeypatch.setattr(config_module.Settings, "qdrant_url", "http://localhost:6333")
    monkeypatch.setattr(config_module.Settings, "speaker_profile_path", "~/.jarvis/voice/speaker_profile.json")

    config_module.get_settings.cache_clear()
    settings_1 = config_module.get_settings()
    settings_2 = config_module.get_settings()

    assert settings_1 is settings_2
    assert settings_1.openai_api_key == "test-key"
    assert settings_1.openai_realtime_voice == "ash"
    assert settings_1.google_enabled is True
    assert settings_1.qdrant_enabled is True
    assert settings_1.speaker_profile_path.endswith(".jarvis/voice/speaker_profile.json")

    config_module.get_settings.cache_clear()


def test_personal_info_reads_home_settings(temp_home):
    settings_path = temp_home / ".jarvis" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps({"personal": {"name": "Amine", "timezone": "Europe/Paris"}})
    )

    settings = config_module.Settings()
    assert settings.personal_info == {"name": "Amine", "timezone": "Europe/Paris"}


def test_voice_settings_include_activation_defaults(temp_home):
    settings_path = temp_home / ".jarvis" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"voice": {"enabled": True, "wakeWord": "Jarvis"}}))

    settings = config_module.Settings()
    voice = settings.voice_settings
    default_intro = str(Path(__file__).resolve().parents[2] / "audio" / "jarvis_guitar_music.m4a")

    assert voice["enabled"] is True
    assert voice["wakeWord"] == "Jarvis"
    assert voice["clapEnabled"] is True
    assert voice["introSoundPath"] == default_intro
    assert voice["activationGreeting"] == "Welcome home, sir."
    assert voice["announceStatus"] is True
    assert voice["announceCalendar"] is True

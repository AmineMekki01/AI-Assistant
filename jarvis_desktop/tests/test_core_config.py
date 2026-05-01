from __future__ import annotations

import json

from app.core import config as config_module


def test_get_settings_reads_environment_and_caches(monkeypatch):
    monkeypatch.setattr(config_module.Settings, "openai_api_key", "test-key")
    monkeypatch.setattr(config_module.Settings, "openai_realtime_voice", "onyx")
    monkeypatch.setattr(config_module.Settings, "google_client_id", "client-id")
    monkeypatch.setattr(config_module.Settings, "google_client_secret", "client-secret")
    monkeypatch.setattr(config_module.Settings, "qdrant_url", "http://localhost:6333")

    config_module.get_settings.cache_clear()
    settings_1 = config_module.get_settings()
    settings_2 = config_module.get_settings()

    assert settings_1 is settings_2
    assert settings_1.openai_api_key == "test-key"
    assert settings_1.openai_realtime_voice == "onyx"
    assert settings_1.google_enabled is True
    assert settings_1.qdrant_enabled is True

    config_module.get_settings.cache_clear()


def test_personal_info_reads_home_settings(temp_home):
    settings_path = temp_home / ".jarvis" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps({"personal": {"name": "Amine", "timezone": "Europe/Paris"}})
    )

    settings = config_module.Settings()
    assert settings.personal_info == {"name": "Amine", "timezone": "Europe/Paris"}

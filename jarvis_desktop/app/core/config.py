"""Configuration management for JARVIS Desktop"""

import json
import os
from functools import lru_cache
from pathlib import Path


class Settings:
    """Application settings loaded from environment variables."""
    
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_realtime_model: str = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-mini")
    openai_realtime_voice: str = os.getenv("OPENAI_REALTIME_VOICE", "alloy")
    openai_utility_model: str = os.getenv("OPENAI_UTILITY_MODEL", "gpt-5.4-nano")
    openai_embedding_model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_token_path: str = os.path.expanduser("~/.jarvis/google_token.json")
    
    obsidian_vault_path: str = os.path.expanduser(os.getenv("OBSIDIAN_VAULT_PATH", "~/Documents/Obsidian"))
    
    qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_memory_collection: str = os.getenv("QDRANT_MEMORY_COLLECTION", "long_term_memory")
    qdrant_vault_collection: str = os.getenv("QDRANT_VAULT_COLLECTION", "obsidian_vault")
    
    jarvis_user_id: str = os.getenv("JARVIS_USER_ID", "user")
    
    @property
    def personal_info(self) -> dict:
        """Load personal info from saved settings."""
        settings_path = Path.home() / ".jarvis" / "settings.json"
        if settings_path.exists():
            try:
                with open(settings_path) as f:
                    settings = json.load(f)
                    return settings.get("personal", {})
            except Exception:
                pass
        return {}

    @property
    def voice_settings(self) -> dict:
        """Load voice wake-word settings from saved settings."""
        settings_path = Path.home() / ".jarvis" / "settings.json"
        if settings_path.exists():
            try:
                with open(settings_path) as f:
                    settings = json.load(f)
                    voice = settings.get("voice", {})
                    return {
                        "enabled": bool(voice.get("enabled", True)),
                        "wakeWord": voice.get("wakeWord", "Hey JARVIS"),
                        "sensitivity": float(voice.get("sensitivity", 0.5)),
                    }
            except Exception:
                pass
        return {
            "enabled": True,
            "wakeWord": "Hey JARVIS",
            "sensitivity": 0.5,
        }
    
    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)
    
    @property
    def tavily_enabled(self) -> bool:
        return bool(self.tavily_api_key)
    
    @property
    def qdrant_enabled(self) -> bool:
        return bool(self.qdrant_url)


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

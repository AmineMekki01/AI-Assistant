#!/usr/bin/env python3
"""JARVIS launcher and a short-lived compatibility façade.

Production code starts :class:`AssistantApplication`. The façade preserves the
former ``JarvisWebSocketApp`` import while callers migrate to components.
"""
from __future__ import annotations

import asyncio
import queue
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent / ".env"
# Configuration defaults are evaluated at import time. Load dotenv first, while
# respecting environment values injected by the shell, Docker, or the app.
load_dotenv(_ENV_PATH, override=False)

from app.application.assistant import AssistantApplication
from app.core import music_state
from app.core.config import Settings, get_settings
from app.core.realtime_session import RealtimeSession
from app.core.websocket_bridge import create_bridge, get_bridge
from app.runtime import REGISTRY
from app.voice.listener import NativeVoiceController

MUSIC_DUCK_TARGET_VOLUME = Settings.music_duck_target_volume


class JarvisWebSocketApp(AssistantApplication):
    """Compatibility adapter for the previous monolithic application API.

    New code uses ``AssistantApplication`` and accesses its ``voice``,
    ``audio``, ``activation``, ``mail``, and ``reminders`` components directly.
    """

    _VOICE_MEMBERS = {
        "_native_voice_thread", "_native_voice_stop", "_native_voice_armed",
        "_native_music_playing", "_frontend_recording", "_input_turn_id",
        "_input_stream", "_native_voice_last_activity", "_native_recording_started_at",
        "_native_voice_cooldown_until", "_native_mic_resume_at",
        "_native_listening_window_until", "_native_recording_has_speech",
        "_native_background_energy", "_native_pre_roll_audio", "_native_speech_streak",
        "_native_voice_last_status", "_native_voice_last_skip_reason",
        "_native_voice_last_heartbeat", "_native_last_frame_energy",
        "_native_clap_cooldown_until", "_native_voice_frame_count",
        "_native_voice_started_at", "_recording_audio_buffer", "_audio_chunk_count",
        "_total_audio_sent", "_speaker_verifier",
    }
    _AUDIO_MEMBERS = {
        "_playback_active", "_speech_active", "_audio_stop", "_audio_generation",
        "_jarvis_last_output_at", "_music_volume_before_duck", "audio_queue",
        "audio_thread", "is_playing", "_speaking_timer",
    }
    _VOICE_METHODS = {
        "_voice_settings", "_get_speaker_verifier", "_warm_speaker_verifier_cache",
        "_start_speaker_verifier_warmup", "_detect_clap_trigger", "_should_ignore_trigger",
        "_reset_native_recording_state", "_music_blocks_clap_trigger", "_set_voice_status",
        "_trace_native_voice_skip", "_trace_native_voice_heartbeat", "_send_voice_debug",
        "_strip_wake_word", "_update_background_energy", "_native_speech_flags",
        "_flush_pending_recording", "_offer_input", "_start_input_stream",
        "_commit_buffered_audio",
    }
    _AUDIO_METHODS = {
        "_query_system_volume", "_set_system_volume", "_update_music_listening_volume",
        "_set_playback_active", "_publish_speaking_state", "_clear_audio_queue",
        "_audio_player_thread", "_audio_player_loop",
    }
    _ACTIVATION_METHODS = {
        "_activation_voice_settings", "_wait_for_session_ready", "_play_activation_sound",
        "_speak_activation_text", "_build_activation_summary",
        "_build_activation_summary_fallback", "_trigger_activation_sequence",
        "_run_activation_sequence",
    }
    _METHOD_ALIASES = {
        "_on_input_audio": ("voice", "receive_audio"),
        "_on_commit_audio": ("voice", "commit_recording"),
        "_on_recording_start": ("voice", "start_recording"),
        "_on_recording_cancel": ("voice", "cancel_recording"),
        "_native_voice_loop": ("voice", "capture.run"),
        "_on_speaking": ("audio", "set_speaking"),
        "_on_audio": ("audio", "receive_audio"),
        "_dispatch_orchestrator_turn": ("app", "dispatch_text"),
    }

    def __init__(self):
        super().__init__(
            settings=get_settings(), registry=REGISTRY,
            session_factory=RealtimeSession, bridge_factory=create_bridge,
        )
        # The legacy app re-read settings when an activation started. Preserve
        # that behaviour only for this adapter; the production composition root
        # intentionally receives one explicit Settings instance.
        self.activation._activation_voice_settings = self._legacy_activation_voice_settings

    def _legacy_activation_voice_settings(self) -> dict:
        voice = get_settings().voice_settings
        return {
            "enabled": bool(voice.get("enabled", True)),
            "wakeWord": str(voice.get("wakeWord") or "Hey JARVIS").strip() or "Hey JARVIS",
            "sensitivity": float(voice.get("sensitivity", 0.5)),
            "clapEnabled": bool(voice.get("clapEnabled", True)),
            "introSoundPath": str(voice.get("introSoundPath") or "").strip(),
            "activationGreeting": str(voice.get("activationGreeting") or "Welcome home, sir.").strip() or "Welcome home, sir.",
            "announceStatus": bool(voice.get("announceStatus", True)),
            "announceCalendar": bool(voice.get("announceCalendar", True)),
        }

    @staticmethod
    def _native_silence_timeout(recording_duration: float) -> float:
        return NativeVoiceController._native_silence_timeout(recording_duration)

    def __getattr__(self, name):
        if name in self._VOICE_MEMBERS or name in self._VOICE_METHODS:
            return getattr(self.voice, name)
        if name in self._AUDIO_MEMBERS or name in self._AUDIO_METHODS:
            return getattr(self.audio, name)
        if name in self._ACTIVATION_METHODS:
            return getattr(self.activation, name)
        target = self._METHOD_ALIASES.get(name)
        if target:
            component, path = target
            value = self if component == "app" else getattr(self, component)
            for part in path.split("."):
                value = getattr(value, part)
            return value
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if "voice" in self.__dict__ and (name in self._VOICE_MEMBERS or name in self._VOICE_METHODS):
            setattr(self.voice, name, value)
            return
        if "audio" in self.__dict__ and (name in self._AUDIO_MEMBERS or name in self._AUDIO_METHODS):
            setattr(self.audio, name, value)
            return
        if "activation" in self.__dict__ and name in self._ACTIVATION_METHODS:
            setattr(self.activation, name, value)
            return
        target = self._METHOD_ALIASES.get(name)
        if target and target[0] != "app" and target[1].count(".") == 0 and target[0] in self.__dict__:
            setattr(getattr(self, target[0]), target[1], value)
            return
        super().__setattr__(name, value)


def main() -> None:
    settings = get_settings()
    if not settings.openai_api_key:
        raise SystemExit(f"OPENAI_API_KEY is not set. Configure it in {_ENV_PATH}.")
    AssistantApplication(settings=settings).start()


if __name__ == "__main__":
    main()

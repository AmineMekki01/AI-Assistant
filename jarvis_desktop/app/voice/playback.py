"""PCM playback, speaking-state ownership, and music volume ducking."""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING

from app.core import music_state

if TYPE_CHECKING:
    from app.application.assistant import AssistantApplication


def is_music_playing(force_refresh: bool = False) -> bool:
    return music_state.is_music_playing(force_refresh=force_refresh)


class AudioPlayback:
    """PCM playback, speaking-state ownership, and music volume ducking."""

    def __init__(self, app: AssistantApplication):
        self.app = app
        self._playback_active = False
        self._speech_active = False
        self._audio_stop = threading.Event()
        self._audio_generation = 0
        self._jarvis_last_output_at = 0.0
        self._music_volume_before_duck: int | None = None
        self.audio_queue = queue.Queue()
        self.audio_thread: threading.Thread = None
        self.is_playing = False
        self._speaking_timer = None

    def _query_system_volume(self) -> int | None:
        if sys.platform != "darwin":
            return None

        try:
            proc = subprocess.run(
                ["osascript", "-e", 'output volume of (get volume settings)'],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
        except Exception as e:
            print(f"⚠️  [VOICE] Failed to query system volume: {e}", flush=True)
            return None

        if proc.returncode != 0:
            return None

        try:
            return int(float((proc.stdout or "").strip()))
        except Exception:
            return None

    def _set_system_volume(self, level: int) -> bool:
        if sys.platform != "darwin":
            return False

        clamped = max(0, min(100, int(level)))
        try:
            proc = subprocess.run(
                ["osascript", "-e", f"set volume output volume {clamped}"],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
        except Exception as e:
            print(f"⚠️  [VOICE] Failed to set system volume: {e}", flush=True)
            return False

        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            print(f"⚠️  [VOICE] System volume change failed: {stderr}", flush=True)
            return False

        return True

    def _update_music_listening_volume(self, music_playing: bool, allow_passive_followup: bool) -> None:
        should_duck = music_playing and (allow_passive_followup or self.app.voice._native_voice_armed) and not (self.app.bridge and self.app.bridge.is_speaking)

        if should_duck:
            if self._music_volume_before_duck is not None:
                return

            current_volume = self._query_system_volume()
            if current_volume is None:
                return

            target_volume = min(current_volume, self.app.settings.music_duck_target_volume)
            if target_volume >= current_volume:
                return

            if self._set_system_volume(target_volume):
                self._music_volume_before_duck = current_volume
                print(
                    f"🔉 [VOICE] Ducking Music volume from {current_volume}% to {target_volume}% while listening",
                    flush=True,
                )
            return

        if self._music_volume_before_duck is None:
            return

        previous_volume = self._music_volume_before_duck
        self._music_volume_before_duck = None
        if self._set_system_volume(previous_volume):
            print(f"🔊 [VOICE] Restored Music volume to {previous_volume}%", flush=True)

    def set_speaking(self, is_speaking: bool):
        """Handle speaking-state updates from the realtime session."""
        self._speech_active = is_speaking
        self._publish_speaking_state()

    def _set_playback_active(self, active: bool) -> None:
        self._playback_active = active
        self._publish_speaking_state()

    def _publish_speaking_state(self) -> None:
        is_speaking = self._speech_active or self._playback_active
        if self.app.bridge:
            self.app.bridge.set_speaking_state(is_speaking)
        if not is_speaking:
            self._jarvis_last_output_at = time.time()
            self.app.voice._native_mic_resume_at = time.time() + self.app.settings.voice_mic_resume_seconds
            self.app.voice._native_listening_window_until = time.time() + self.app.settings.voice_followup_seconds
        else:
            # The speaking flag owns the mute. Never leave an infinite second
            # gate behind when playback is interrupted or fails.
            self.app.voice._native_mic_resume_at = 0.0

    def receive_audio(self, audio_bytes: bytes):
        """Handle audio OUTPUT from Realtime API (JARVIS speaking)."""
        if self.app.bridge and self.app.bridge.is_recording:
            self._clear_audio_queue()
            return

        self._set_playback_active(True)
        self.audio_queue.put(audio_bytes)
        self._jarvis_last_output_at = time.time()

    def _clear_audio_queue(self):
        """Drop any queued assistant audio when the user interrupts."""
        self._audio_generation += 1
        cleared = 0
        while True:
            try:
                self.audio_queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break

        self._set_playback_active(False)
        if cleared:
            print(f"🧹 Cleared {cleared} queued audio chunk(s)")

    def _audio_player_thread(self):
        while not self._audio_stop.is_set():
            self._audio_player_loop()
            if self._audio_stop.wait(1.0):
                break

    def _audio_player_loop(self):
        """Only the PCM player can release its playback mute; TTS owns its own."""
        p = stream = None
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            stream = p.open(format=pyaudio.paInt16, channels=1, rate=24000,
                            output=True, frames_per_buffer=2048)
            print("🔊 Audio output ready")
            while not self._audio_stop.is_set():
                try:
                    audio_chunk = self.audio_queue.get(timeout=0.05)
                    generation = self._audio_generation
                    for offset in range(0, len(audio_chunk), 4800):
                        if generation != self._audio_generation:
                            break
                        stream.write(audio_chunk[offset:offset + 4800])
                except queue.Empty:
                    response_active = bool(self.app.session and getattr(self.app.session, "_response_active", False))
                    if self._playback_active and not response_active:
                        self._set_playback_active(False)
        except Exception as e:
            print(f"⚠️ Audio output failed; reopening device: {e}", flush=True)
            self._clear_audio_queue()
        finally:
            self._set_playback_active(False)
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            if p is not None:
                p.terminate()

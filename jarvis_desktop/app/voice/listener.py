"""Native listener lifecycle, authentication, and input turn ownership."""
from __future__ import annotations

import asyncio
import importlib.util
import re
import threading
import time
from collections import deque
from typing import TYPE_CHECKING

from app.core import music_state
from app.core.voice_input import RealtimeInputStream

if TYPE_CHECKING:
    from app.application.assistant import AssistantApplication


def is_music_playing(force_refresh: bool = False) -> bool:
    return music_state.is_music_playing(force_refresh=force_refresh)


class NativeVoiceController:
    """Native listener lifecycle, authentication, and input turn ownership."""

    def __init__(self, app: AssistantApplication):
        self.app = app
        self._native_voice_thread: threading.Thread = None
        self._native_voice_stop = threading.Event()
        self._native_voice_armed = False
        self._native_music_playing = False
        self._frontend_recording = False
        self._input_turn_id = 0
        self._input_stream = RealtimeInputStream(
            lambda: self.app.session, self._get_speaker_verifier, self.app._on_status
        )
        self._native_voice_last_activity = 0.0
        self._native_recording_started_at = 0.0
        self._native_voice_cooldown_until = 0.0
        self._native_mic_resume_at = 0.0
        self._native_listening_window_until = 0.0
        self._native_recording_has_speech = False
        self._native_background_energy = 0.0
        self._native_pre_roll_audio: deque[bytes] = deque(maxlen=6)
        self._native_speech_streak = 0
        self._native_voice_last_status = ""
        self._native_voice_last_skip_reason = ""
        self._native_voice_last_heartbeat = 0.0
        self._native_last_frame_energy = 0.0
        self._native_clap_cooldown_until = 0.0
        self._native_voice_frame_count = 0
        self._native_voice_started_at = 0.0
        self._recording_audio_buffer = []
        self._audio_chunk_count = 0
        self._total_audio_sent = 0
        self._speaker_verifier = None
        from .capture import MicrophoneCapture
        self.capture = MicrophoneCapture(app)

    @staticmethod
    def _normalize_wake_word(text: str) -> str:
        return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9\s]', ' ', (text or "").lower())).strip()

    def _voice_settings(self) -> dict:
        try:
            voice = self.app.settings.voice_settings
            return {
                "enabled": bool(voice.get("enabled", True)),
                "wakeWord": voice.get("wakeWord", "Hey JARVIS"),
                "sensitivity": float(voice.get("sensitivity", 0.5)),
                "clapEnabled": bool(voice.get("clapEnabled", True)),
                "introSoundPath": str(voice.get("introSoundPath") or "").strip(),
                "activationGreeting": str(voice.get("activationGreeting") or "Welcome home, sir.").strip() or "Welcome home, sir.",
                "announceStatus": bool(voice.get("announceStatus", True)),
                "announceCalendar": bool(voice.get("announceCalendar", True)),
            }
        except Exception as e:
            print(f"⚠️  [VOICE] Failed to load voice settings: {e}")
            return {
                "enabled": True,
                "wakeWord": "Hey JARVIS",
                "sensitivity": 0.5,
                "clapEnabled": True,
                "introSoundPath": "",
                "activationGreeting": "Welcome home, sir.",
                "announceStatus": True,
                "announceCalendar": True,
            }

    @staticmethod
    def _native_voice_dependencies() -> list[str]:
        required = ["openwakeword", "pyaudio"]
        missing = [name for name in required if importlib.util.find_spec(name) is None]
        return missing

    def _get_speaker_verifier(self):
        if self._speaker_verifier is False:
            return None
        if self._speaker_verifier is None:
            try:
                from app.core.speaker_verification import SpeakerVerifier

                self._speaker_verifier = SpeakerVerifier.from_environment()
                if self._speaker_verifier is None:
                    self._speaker_verifier = False
            except Exception as e:
                print(f"⚠️  [VOICE] Speaker verification unavailable: {e}", flush=True)
                raise RuntimeError('Speaker verification unavailable; voice commands blocked') from e
        return self._speaker_verifier if self._speaker_verifier is not False else None

    def _warm_speaker_verifier_cache(self) -> None:
        try:
            verifier = self._get_speaker_verifier()
            if verifier is None:
                return
            warmed = verifier.preload()
            if warmed:
                print(f"✅ [VOICE] Speaker profile warmed in memory: {verifier.profile_path}", flush=True)
            else:
                print(f"ℹ️  [VOICE] No speaker profile to warm at {verifier.profile_path}", flush=True)
        except Exception as e:
            print(f"⚠️  [VOICE] Speaker warmup failed: {e}", flush=True)

    def _start_speaker_verifier_warmup(self) -> None:
        thread = threading.Thread(target=self._warm_speaker_verifier_cache, daemon=True)
        thread.start()

    def _detect_clap_trigger(self, frame_energy: float) -> bool:
        if self.app.settings.speaker_verification_enabled:
            return False  # A clap cannot authenticate the enrolled speaker.
        voice = self.app.activation._activation_voice_settings()
        if not voice["enabled"] or not voice["clapEnabled"]:
            return False

        now = time.time()
        if now < self._native_clap_cooldown_until:
            return False
        if self.app.bridge and self.app.bridge.is_speaking:
            return False

        # Block clap detection for the first 10s after the mic stream opens.
        # Startup clicks, pops, and settling noise consistently trigger false
        # positives in the first few seconds.
        if self._native_voice_started_at and (time.time() - self._native_voice_started_at) < 10.0:
            return False

        spike_threshold = max(0.12, self._native_background_energy * 5.0)
        if frame_energy < spike_threshold:
            return False

        if self._native_last_frame_energy > frame_energy * 0.8:
            return False

        self._native_clap_cooldown_until = now + 1.2
        return True

    def _should_ignore_trigger(self) -> bool:
        return bool(self.app.bridge and self.app.bridge.is_speaking)

    def _reset_native_recording_state(self) -> None:
        self._recording_audio_buffer = []
        self._audio_chunk_count = 0
        self._total_audio_sent = 0
        self._native_recording_has_speech = False
        self._native_voice_armed = False
        self._native_voice_last_activity = 0.0
        self._native_recording_started_at = 0.0
        self._native_speech_streak = 0
        self._native_pre_roll_audio.clear()
        if self.app.bridge:
            self.app.bridge.set_recording_state(False)

    def _music_blocks_clap_trigger(self, music_playing: bool) -> bool:
        return bool(music_playing and not music_state.voice_followup_override_active())

    @staticmethod
    def _native_silence_timeout(recording_duration: float) -> float:
        """Return an adaptive end-of-speech timeout.

        Short commands still commit quickly, but longer utterances get more
        time so slower speakers and mid-sentence pauses are less likely to be
        cut off.
        """
        if recording_duration < 1.5:
            return 1.2
        if recording_duration < 4.0:
            return 1.8
        return 2.1

    def _set_voice_status(self, state: str, message: str) -> None:
        status_key = f"{state}:{message}"
        if status_key == self._native_voice_last_status:
            return
        self._native_voice_last_status = status_key
        if self.app.bridge:
            self.app.bridge.send_status(state, message)

    def _trace_native_voice_skip(self, reason: str) -> None:
        if reason == self._native_voice_last_skip_reason:
            return
        self._native_voice_last_skip_reason = reason
        print(f"🔎 [VOICE] Native listener paused: {reason}", flush=True)

    def _trace_native_voice_heartbeat(self, *, armed: bool, music_playing: bool, allow_passive_followup: bool) -> None:
        now = time.time()
        if now - self._native_voice_last_heartbeat < 5.0:
            return
        self._native_voice_last_heartbeat = now
        speaking = bool(self.app.bridge and self.app.bridge.is_speaking)
        print(
            "🫀 [VOICE] heartbeat | "
            f"armed={armed} speaking={speaking} music={music_playing} "
            f"passive_followup={allow_passive_followup} "
            f"cooldown_left={max(0.0, self._native_voice_cooldown_until - now):.1f}s "
            f"mic_resume_left={max(0.0, self._native_mic_resume_at - now):.1f}s "
            f"listen_window_left={max(0.0, self._native_listening_window_until - now):.1f}s",
            flush=True,
        )

        self._send_voice_debug(
            status="recording" if self._native_voice_armed else ("passive_followup" if allow_passive_followup else "listening"),
            armed=armed,
            music_playing=music_playing,
            allow_passive_followup=allow_passive_followup,
            skip_reason=self._native_voice_last_skip_reason,
        )

    def _send_voice_debug(
        self,
        *,
        status: str,
        armed: bool,
        music_playing: bool,
        allow_passive_followup: bool,
        skip_reason: str,
    ) -> None:
        if not self.app.bridge:
            return

        now = time.time()
        self.app.bridge.send_voice_debug({
            "status": status,
            "armed": armed,
            "speaking": bool(self.app.bridge and self.app.bridge.is_speaking),
            "musicPlaying": music_playing,
            "passiveFollowup": allow_passive_followup,
            "recording": bool(self.app.bridge and self.app.bridge.is_recording),
            "skipReason": skip_reason,
            "cooldownRemaining": max(0.0, self._native_voice_cooldown_until - now),
            "micResumeRemaining": max(0.0, self._native_mic_resume_at - now),
            "listenWindowRemaining": max(0.0, self._native_listening_window_until - now),
        })

    def start(self) -> None:
        if self._native_voice_thread and self._native_voice_thread.is_alive():
            return

        missing = self._native_voice_dependencies()
        if missing:
            message = f"Native wake-word disabled: missing Python packages: {', '.join(missing)}"
            print(f"⚠️  [VOICE] {message}", flush=True)
            self._set_voice_status("error", message)
            return

        self._native_voice_stop.clear()
        self._native_voice_thread = threading.Thread(target=self._native_voice_supervisor, daemon=True)
        self._native_voice_thread.start()
        threading.Thread(target=self._native_voice_housekeeping, daemon=True).start()
        print("🎙️ Native wake-word listener starting", flush=True)

    def _native_voice_supervisor(self) -> None:
        while not self._native_voice_stop.is_set():
            self.app.voice.capture.run()
            if self._native_voice_stop.wait(3.0):
                break
            self._set_voice_status("error", "Reopening microphone and wake-word listener…")

    def _native_voice_housekeeping(self) -> None:
        # AppleScript can take several seconds. Never run it on the capture loop.
        while not self._native_voice_stop.is_set():
            try:
                self._native_music_playing = is_music_playing()
                followup = time.time() < self._native_listening_window_until or music_state.voice_followup_override_active()
                self.app.audio._update_music_listening_volume(self._native_music_playing, followup)
            except Exception as e:
                print(f"⚠️ [VOICE] Music state check failed: {e}", flush=True)
            self._native_voice_stop.wait(1.0)

    def stop(self) -> None:
        self._native_voice_stop.set()

    def _strip_wake_word(self, transcript: str, wake_word: str) -> str:
        candidates = [wake_word, "hey jarvis", "jarvis"]
        pattern = r"^(?:" + "|".join(re.escape(word) for word in candidates if word) + r")\b[\s,.:!?—-]*"
        return re.sub(pattern, "", transcript.strip(), count=1, flags=re.IGNORECASE)

    def _update_background_energy(self, energy: float, is_speech: bool) -> None:
        # Learning speech as noise progressively makes the next turn inaudible.
        if not is_speech:
            self._native_background_energy = self._native_background_energy * 0.98 + energy * 0.02

    def _native_speech_flags(self, energy: float, probability: float | None) -> tuple[bool, bool]:
        if probability is not None:
            # Speech can be quiet. Model confidence, not loudness, determines
            # whether a word resets the end-of-utterance timer. A lower hold
            # threshold avoids cutting off softer words after speech starts.
            return probability >= 0.25, probability >= 0.5
        threshold = max(0.0035, self._native_background_energy * 3.5)
        start_threshold = max(0.008, self._native_background_energy * 5.0, threshold * 1.5)
        return energy >= threshold, energy >= start_threshold

    def _flush_pending_recording(self) -> None:
        """Commit any buffered native recording once the session is available."""
        if not self.app.session or not self.app.event_loop or not self._recording_audio_buffer:
            return

        print(f"📨 [VOICE] Flushing pending native recording ({len(self._recording_audio_buffer)} chunk(s))", flush=True)
        self.commit_recording()

    def receive_audio(self, audio_bytes: bytes):
        """Collect 16 kHz PCM for the current recording only."""
        if not (self.app.bridge and self.app.bridge.is_recording):
            return
        if self._total_audio_sent + len(audio_bytes) > int(self.app.settings.voice_max_recording_seconds * 16000 * 2):
            self.app.bridge.set_recording_state(False)
            self._native_voice_armed = False
            self.commit_recording()
            return
        self._recording_audio_buffer.append(audio_bytes)
        self._audio_chunk_count += 1
        self._total_audio_sent += len(audio_bytes)
        self._offer_input('audio', audio_bytes)

    def _offer_input(self, kind: str, audio: bytes = b'') -> None:
        if self.app.event_loop is not None:
            self.app.event_loop.call_soon_threadsafe(self._input_stream.offer, kind, self._input_turn_id, audio)

    def _start_input_stream(self, chunks=()) -> None:
        self._input_turn_id += 1
        self._offer_input('start')
        for chunk in chunks:
            self._offer_input('audio', chunk)

    async def _commit_buffered_audio(self, buffered_chunks):
        """Compatibility path for pre-buffered callers; uses the same voice model."""
        self._input_turn_id += 1
        turn = self._input_turn_id
        self._input_stream.offer('start', turn)
        for chunk in buffered_chunks:
            self._input_stream.offer('audio', turn, chunk)
        self._input_stream.offer('end', turn)
        await self._input_stream._queue.join()

    def commit_recording(self):
        """Commit the already-streamed recording without blocking capture."""
        self._frontend_recording = False
        self._recording_audio_buffer = []
        self._total_audio_sent = 0
        self._audio_chunk_count = 0
        self._offer_input('end')

    def start_recording(self):
        """Reset state when recording starts."""
        print("🔄 Recording started - resetting response state")
        self._frontend_recording = True
        self._native_voice_armed = False
        self._native_pre_roll_audio.clear()
        self._native_speech_streak = 0
        self._recording_audio_buffer = []
        self._audio_chunk_count = 0
        self._total_audio_sent = 0
        if self.app.session:
            future = asyncio.run_coroutine_threadsafe(
                self.app.session.interrupt_active_response(),
                self.app.event_loop,
            )
            try:
                future.result(timeout=0.5)
            except Exception as e:
                print(f"⚠️  Error interrupting active response: {e}")

        if self.app.bridge:
            if self.app.audio._speaking_timer:
                self.app.audio._speaking_timer.cancel()
                self.app.audio._speaking_timer = None
            self.app.audio.set_speaking(False)
            self._native_mic_resume_at = 0.0
            print("🔊 Speaking state cleared - ready for input")

        self.app.audio._clear_audio_queue()
        self._start_input_stream()

    def cancel_recording(self):
        self._offer_input('cancel')
        self._frontend_recording = False
        self._reset_native_recording_state()

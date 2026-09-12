#!/usr/bin/env python3
"""
JARVIS Desktop - WebSocket Edition
Connects to React frontend via WebSocket
"""

import os
import sys
import asyncio
import threading
import queue
import subprocess
from collections import deque
import re
import time
import importlib.util
import io
import wave
from pathlib import Path
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent.resolve()
NATIVE_MIC_RESUME_DELAY_SECONDS = 0.2
TURN_TIMEOUT_SECONDS = 120.0
MAX_RECORDING_SECONDS = 120.0
MUSIC_DUCK_TARGET_VOLUME = 30

env_path = SCRIPT_DIR / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print(f"✅ Loaded .env from {env_path}")
else:
    print(f"⚠️  Warning: .env file not found at {env_path}")

sys.path.insert(0, str(SCRIPT_DIR))

from app.core.realtime_session import RealtimeSession
from app.core.config import get_settings
from app.core.voice_input import RealtimeInputStream
from app.core import music_state
from app.core.websocket_bridge import create_bridge, get_bridge
from app.runtime import REGISTRY


def is_music_playing(force_refresh: bool = False) -> bool:
    return music_state.is_music_playing(force_refresh=force_refresh)


class JarvisWebSocketApp:
    """JARVIS voice assistant with WebSocket frontend."""
    
    def __init__(self):
        self.session: RealtimeSession = None
        self.event_loop: asyncio.AbstractEventLoop = None
        self.session_thread: threading.Thread = None
        self._native_voice_thread: threading.Thread = None
        self._native_voice_stop = threading.Event()
        self._native_voice_armed = False
        self._commit_in_progress = False
        self._commit_lock = threading.Lock()
        self._turn_lock = threading.Lock()
        self._pending_turns: deque[str] = deque()
        self._native_music_playing = False
        self._frontend_recording = False
        self._playback_active = False
        self._speech_active = False
        self._audio_stop = threading.Event()
        self._audio_generation = 0
        self._input_turn_id = 0
        self._input_stream = RealtimeInputStream(
            lambda: self.session, self._get_speaker_verifier, self._on_status
        )
        self._native_voice_last_activity = 0.0
        self._native_recording_started_at = 0.0
        self._native_voice_cooldown_until = 0.0
        self._jarvis_last_output_at = 0.0
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
        self._activation_sequence_running = False
        self._music_volume_before_duck: int | None = None
        self.pending_mail_draft = None
        self._recording_audio_buffer = []
        self._audio_chunk_count = 0
        self._total_audio_sent = 0
        self._last_user_transcript = ""
        self._last_mail_draft_raw_text = ""
        self._mail_draft_pending = False
        self._pending_voice_texts: queue.Queue[str] = queue.Queue()
        self._speaker_verifier = None

        # Realtime owns conversation/reasoning; delegated agents remain registry tools.
        self._orchestrator_turn_in_progress = False
        
        self.audio_queue = queue.Queue()
        self.audio_thread: threading.Thread = None
        self.is_playing = False
        
        self.bridge = None
        
        self._speaking_timer = None
        self._reminder_poller_thread: threading.Thread | None = None
        self._reminder_poller_stop = threading.Event()
        self._reminder_last_alerted: dict[str, float] = {}

    @staticmethod
    def _normalize_wake_word(text: str) -> str:
        return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9\s]', ' ', (text or "").lower())).strip()

    def _voice_settings(self) -> dict:
        try:
            voice = get_settings().voice_settings
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
        should_duck = music_playing and (allow_passive_followup or self._native_voice_armed) and not (self.bridge and self.bridge.is_speaking)

        if should_duck:
            if self._music_volume_before_duck is not None:
                return

            current_volume = self._query_system_volume()
            if current_volume is None:
                return

            target_volume = min(current_volume, MUSIC_DUCK_TARGET_VOLUME)
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

    def _activation_voice_settings(self) -> dict:
        voice = self._voice_settings()
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
    def _summarize_calendar_output(raw_output: str) -> str:
        lines = [line.strip() for line in (raw_output or "").splitlines() if line.strip()]
        if not lines:
            return ""

        if lines[0].lower().startswith("error"):
            return ""

        if lines[0].lower().startswith("no events"):
            return "No upcoming calendar events."

        items: list[str] = []
        for line in lines:
            if line.startswith("──"):
                continue
            if "event(s)" in line and line.endswith(":"):
                continue

            cleaned = line.lstrip("•").strip()
            if "|" in cleaned:
                when_part, summary_part = cleaned.split("|", 1)
                when = when_part.replace("->", "to").strip()
                summary = summary_part.strip()
                if summary:
                    items.append(f"{summary} at {when}")
            elif cleaned:
                items.append(cleaned)

            if len(items) >= 2:
                break

        if not items:
            return ""
        if len(items) == 1:
            return f"Your next calendar item is {items[0]}."
        return "Your next calendar items are " + "; ".join(items) + "."

    async def _wait_for_session_ready(self, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.session is not None:
                return True
            await asyncio.sleep(0.1)
        return self.session is not None

    async def _play_activation_sound(self, sound_path: str) -> bool:
        if not sound_path:
            return False

        path = Path(sound_path).expanduser()
        if not path.exists():
            print(f"ℹ️  [VOICE] Activation sound not found: {path}", flush=True)
            return False

        import shutil

        if not shutil.which("afplay"):
            print("ℹ️  [VOICE] Cannot play activation sound: afplay unavailable", flush=True)
            return False

        process = None
        try:
            volume = os.getenv("JARVIS_ACTIVATION_SOUND_VOLUME", "0.65")
            process = await asyncio.create_subprocess_exec(
                "afplay",
                "-v",
                volume,
                str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), timeout=10.0)
            return process.returncode == 0
        except Exception as e:
            print(f"⚠️  [VOICE] Activation sound playback failed: {e}", flush=True)
            return False
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()

    async def _speak_activation_text(self, text: str) -> None:
        if not text:
            return

        if self.session is None and not await self._wait_for_session_ready(timeout=5.0):
            print("ℹ️  [VOICE] Activation speech skipped: realtime session not ready", flush=True)
            return

        if self.session is not None:
            await self.session.speak(text)

    async def _build_activation_summary(self) -> str:
        try:
            startup_task = (
                "Produce a very short startup briefing for the user. Keep it to 2-4 "
                "short spoken sentences. Cover the current day, the next 24 hours, "
                "urgent calendar items, unread or actionable mail, and any important "
                "notes or reminders that change the startup picture. Do not use "
                "headings or a preface."
            )
            context_parts: list[str] = ["This is the JARVIS startup sequence."]

            try:
                settings = get_settings()
                speaker_verification_enabled = bool(settings.speaker_verification_enabled)
            except Exception:
                speaker_verification_enabled = self._speaker_verifier is not None

            if self.session and getattr(self.session, "_ws_alive", None) and self.session._ws_alive():
                context_parts.append("The realtime connection is online.")
            elif self.session:
                context_parts.append("The realtime connection is still coming online.")
            else:
                context_parts.append("The realtime session is still starting.")

            if speaker_verification_enabled:
                verifier = self._get_speaker_verifier()
                profile_path = getattr(verifier, "profile_path", None) if verifier is not None else None
                if verifier is not None and profile_path is not None and getattr(profile_path, "exists", lambda: False)():
                    context_parts.append("Speaker verification is ready.")
                else:
                    context_parts.append("Speaker verification is enabled, but no profile is enrolled yet.")
            else:
                context_parts.append("Speaker verification is not enabled.")

            voice = self._activation_voice_settings()
            if voice["clapEnabled"]:
                context_parts.append("Clap and wake word are armed.")
            else:
                context_parts.append("Wake word is armed.")

            if voice["announceCalendar"]:
                context_parts.append("Calendar details are allowed in the startup summary.")

            result = await REGISTRY.call(
                "delegate_to_startup_briefing",
                {
                    "task": startup_task,
                    "context": " ".join(context_parts),
                },
            )
            if result.get("ok"):
                summary = str(result.get("result") or "").strip()
                if summary:
                    return summary
                print("ℹ️  [VOICE] Startup briefing agent returned no text; using fallback summary", flush=True)
            else:
                print(
                    f"ℹ️  [VOICE] Startup briefing agent failed: {result.get('error', 'unknown error')}; using fallback summary",
                    flush=True,
                )
        except Exception as e:
            print(f"⚠️  [VOICE] Startup briefing agent lookup failed: {e}; using fallback summary", flush=True)

        return self._build_activation_summary_fallback()

    async def _build_activation_summary_fallback(self) -> str:
        voice = self._activation_voice_settings()
        try:
            settings = get_settings()
            speaker_verification_enabled = bool(settings.speaker_verification_enabled)
        except Exception:
            speaker_verification_enabled = self._speaker_verifier is not None

        parts: list[str] = []

        if self.session and getattr(self.session, "_ws_alive", None) and self.session._ws_alive():
            parts.append("Connections are online.")
        elif self.session:
            parts.append("The realtime connection is coming online.")
        else:
            parts.append("The realtime session is still starting.")

        if speaker_verification_enabled:
            verifier = self._get_speaker_verifier()
            profile_path = getattr(verifier, "profile_path", None) if verifier is not None else None
            if verifier is not None and profile_path is not None and getattr(profile_path, "exists", lambda: False)():
                parts.append("Speaker verification is ready.")
            else:
                parts.append("Speaker verification is enabled, but no profile is enrolled yet.")
        else:
            parts.append("Speaker verification is not enabled.")

        if voice["clapEnabled"]:
            parts.append("Clap and wake word are armed.")
        else:
            parts.append("Wake word is armed.")

        if voice["announceCalendar"]:
            try:
                result = await asyncio.wait_for(REGISTRY.call("calendar_list", {"max_results": 3}), timeout=1.5)
                if result.get("ok"):
                    calendar_summary = self._summarize_calendar_output(str(result.get("result") or ""))
                    if calendar_summary:
                        parts.append(calendar_summary)
            except asyncio.TimeoutError:
                print("ℹ️  [VOICE] Calendar summary timed out; speaking status without events", flush=True)
            except Exception as e:
                print(f"⚠️  [VOICE] Calendar summary failed: {e}", flush=True)

        return " ".join(parts)

    def _trigger_activation_sequence(self, trigger: str) -> None:
        if self._activation_sequence_running:
            return
        if not self.event_loop:
            print(f"ℹ️  [VOICE] Activation trigger ignored: event loop not ready ({trigger})", flush=True)
            return

        self._activation_sequence_running = True
        future = asyncio.run_coroutine_threadsafe(
            asyncio.wait_for(self._run_activation_sequence(trigger), timeout=45.0), self.event_loop
        )

        def _release(_future):
            self._activation_sequence_running = False
            try:
                _future.result()
            except Exception as e:
                print(f"⚠️ [VOICE] Activation ended early: {e}", flush=True)
                self._set_voice_status("connected", "Listening for your request")

        future.add_done_callback(_release)

    async def _run_activation_sequence(self, trigger: str) -> None:
        summary_task = sound_task = None
        try:
            voice = self._activation_voice_settings()
            intro_sound_path = voice["introSoundPath"]
            self._native_voice_cooldown_until = time.time() + 3.0
            self._native_clap_cooldown_until = time.time() + 2.0
            self._native_voice_armed = False
            self._native_recording_has_speech = False
            self._recording_audio_buffer = []
            self._audio_chunk_count = 0
            self._total_audio_sent = 0
            self._native_speech_streak = 0
            self._native_pre_roll_audio.clear()
            self._native_listening_window_until = time.time() + 300.0
            if self.bridge:
                self.bridge.set_recording_state(False)

            summary_task = None
            if voice["announceStatus"]:
                summary_task = asyncio.create_task(self._build_activation_summary())

            sound_task = None
            if intro_sound_path:
                sound_task = asyncio.create_task(self._play_activation_sound(intro_sound_path))

            if summary_task is not None or sound_task is not None:
                await asyncio.sleep(0)

            if self.session is None and not await self._wait_for_session_ready(timeout=5.0):
                print(f"ℹ️  [VOICE] Activation sequence skipped speech: session not ready ({trigger})", flush=True)
                if sound_task is not None:
                    await sound_task
                if summary_task is not None:
                    await summary_task
                return

            if voice["activationGreeting"]:
                await self._speak_activation_text(voice["activationGreeting"])

            if sound_task is not None:
                await sound_task

            if voice["announceStatus"]:
                if summary_task is not None:
                    activation_summary = await summary_task
                else:
                    activation_summary = await self._build_activation_summary()
                if activation_summary:
                    await self._speak_activation_text(activation_summary)
        finally:
            pending = [task for task in (summary_task, sound_task) if task is not None and not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self._activation_sequence_running = False

    def _detect_clap_trigger(self, frame_energy: float) -> bool:
        if get_settings().speaker_verification_enabled:
            return False  # A clap cannot authenticate the enrolled speaker.
        voice = self._activation_voice_settings()
        if not voice["enabled"] or not voice["clapEnabled"]:
            return False

        now = time.time()
        if now < self._native_clap_cooldown_until:
            return False
        if self.bridge and self.bridge.is_speaking:
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
        return bool(self.bridge and self.bridge.is_speaking)

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
        if self.bridge:
            self.bridge.set_recording_state(False)

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
        if self.bridge:
            self.bridge.send_status(state, message)

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
        speaking = bool(self.bridge and self.bridge.is_speaking)
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
        if not self.bridge:
            return

        now = time.time()
        self.bridge.send_voice_debug({
            "status": status,
            "armed": armed,
            "speaking": bool(self.bridge and self.bridge.is_speaking),
            "musicPlaying": music_playing,
            "passiveFollowup": allow_passive_followup,
            "recording": bool(self.bridge and self.bridge.is_recording),
            "skipReason": skip_reason,
            "cooldownRemaining": max(0.0, self._native_voice_cooldown_until - now),
            "micResumeRemaining": max(0.0, self._native_mic_resume_at - now),
            "listenWindowRemaining": max(0.0, self._native_listening_window_until - now),
        })

    def _start_native_voice_listener(self) -> None:
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
            self._native_voice_loop()
            if self._native_voice_stop.wait(3.0):
                break
            self._set_voice_status("error", "Reopening microphone and wake-word listener…")

    def _native_voice_housekeeping(self) -> None:
        # AppleScript can take several seconds. Never run it on the capture loop.
        while not self._native_voice_stop.is_set():
            try:
                self._native_music_playing = is_music_playing()
                followup = time.time() < self._native_listening_window_until or music_state.voice_followup_override_active()
                self._update_music_listening_volume(self._native_music_playing, followup)
            except Exception as e:
                print(f"⚠️ [VOICE] Music state check failed: {e}", flush=True)
            self._native_voice_stop.wait(1.0)

    def _stop_native_voice_listener(self) -> None:
        self._native_voice_stop.set()

    def _send_text_to_session(self, text: str) -> None:
        """Feed typed/injected text to the orchestrator (the single brain)."""
        cleaned = (text or "").strip()
        if not cleaned:
            return
        if not self.event_loop:
            print(f"� [VOICE] Event loop not ready yet, queueing text: {cleaned}")
            self._pending_voice_texts.put(cleaned)
            return
        if self.bridge:
            self.bridge.send_transcript("user", cleaned)
        self._dispatch_orchestrator_turn(cleaned)

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

    def _native_voice_loop(self) -> None:
        try:
            import numpy as np
            import pyaudio
            from openwakeword.model import Model
        except Exception as e:
            print(f"⚠️  [VOICE] Native wake-word listener unavailable: {e}", flush=True)
            self._set_voice_status("error", "Native wake word unavailable")
            return

        voice_settings = self._voice_settings()
        activation_threshold = max(0.2, min(0.8, 1.0 - float(voice_settings.get("sensitivity", 0.5))))
        wake_word = str(voice_settings.get("wakeWord") or "Hey JARVIS")

        print(
            f"🎙️ [VOICE] Starting native wake-word listener | wakeWord={wake_word} threshold={activation_threshold:.2f}",
            flush=True,
        )

        try:
            import openwakeword
            from openwakeword.utils import download_models

            print("🎙️ [VOICE] Ensuring wake-word models are available...", flush=True)
            download_models()

            wake_model = Model(inference_framework="onnx")
            speech_detector = None
            try:
                from openwakeword.vad import VAD
                speech_detector = VAD()
                print("🎙️ [VOICE] Silero speech detection ready", flush=True)
            except Exception as e:
                print(f"⚠️ [VOICE] Speech detector unavailable; using energy fallback: {e}", flush=True)
            model_names = list(wake_model.models.keys())
            print(f"🧠 [VOICE] openWakeWord models loaded: {', '.join(model_names)}", flush=True)
        except Exception as e:
            print(f"⚠️  [VOICE] Failed to load openWakeWord model: {e}", flush=True)
            self._set_voice_status("error", "Wake word model unavailable")
            return

        p = None
        stream = None
        chunk_size = 1280
        min_recording_duration = 0.65
        listen_window_seconds = 300.0  # 5 minutes follow-up window
        speech_frames_required = 3

        captured_audio = queue.Queue(maxsize=4)

        def capture(in_data, frame_count, time_info, status):
            # PortAudio keeps draining the device even while detection is paused.
            # Bound latency; old frames must never be replayed as a new request.
            try:
                captured_audio.put_nowait((time.monotonic(), in_data))
            except queue.Full:
                try:
                    captured_audio.get_nowait()
                except queue.Empty:
                    pass
                try:
                    captured_audio.put_nowait((time.monotonic(), in_data))
                except queue.Full:
                    pass
            return (None, pyaudio.paContinue)

        try:
            p = pyaudio.PyAudio()
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=chunk_size,
                stream_callback=capture,
            )
            print("🎙️ [VOICE] Microphone stream opened (16kHz mono)", flush=True)
        except Exception as e:
            print(f"⚠️  [VOICE] No microphone available: {e}", flush=True)
            self._set_voice_status("error", "Microphone unavailable")
            if p is not None:
                p.terminate()
            return

        self._set_voice_status("connected", f'Wake word armed — say "{wake_word}"')
        self._native_voice_started_at = time.time()
        last_capture_at = time.monotonic()

        try:
            while not self._native_voice_stop.is_set():
                try:
                    captured_at, raw_audio = captured_audio.get(timeout=0.25)
                except queue.Empty:
                    if not stream.is_active() or time.monotonic() - last_capture_at > 2.0:
                        raise RuntimeError("Microphone stream stopped")
                    continue
                last_capture_at = time.monotonic()
                if time.monotonic() - captured_at > 0.3:
                    continue
                music_playing = self._native_music_playing
                shared_music_override_active = music_state.voice_followup_override_active()
                in_listening_window = time.time() < self._native_listening_window_until
                allow_passive_followup = in_listening_window or shared_music_override_active

                if self._frontend_recording:
                    self._native_pre_roll_audio.clear()
                    self._native_speech_streak = 0
                    continue

                if self._activation_sequence_running:
                    self._send_voice_debug(
                        status="activation_sequence",
                        armed=self._native_voice_armed,
                        music_playing=music_playing,
                        allow_passive_followup=False,
                        skip_reason="Activation sequence running",
                    )
                    self._native_pre_roll_audio.clear()
                    self._native_speech_streak = 0
                    continue

                if self.bridge and self.bridge.is_speaking:
                    self._trace_native_voice_skip("JARVIS is speaking")
                    self._send_voice_debug(
                        status="muted_by_speaking",
                        armed=self._native_voice_armed,
                        music_playing=music_playing,
                        allow_passive_followup=False,
                        skip_reason="JARVIS is speaking",
                    )
                    if self._native_voice_armed:
                        print("🔇 [VOICE] JARVIS speaking — aborting recording", flush=True)
                        self._reset_native_recording_state()
                    self._native_pre_roll_audio.clear()
                    self._native_speech_streak = 0
                    continue

                if time.time() < self._native_mic_resume_at:
                    remaining = self._native_mic_resume_at - time.time()
                    self._trace_native_voice_skip(f"Mic resume delay active ({remaining:.2f}s left)")
                    self._send_voice_debug(
                        status="mic_resume_delay",
                        armed=self._native_voice_armed,
                        music_playing=music_playing,
                        allow_passive_followup=False,
                        skip_reason="Mic resume delay",
                    )
                    self._native_pre_roll_audio.clear()
                    self._native_speech_streak = 0
                    continue

                self._native_voice_frame_count += 1

                try:
                    audio = np.frombuffer(raw_audio, dtype=np.int16)
                    if audio.size == 0:
                        continue

                    self._trace_native_voice_heartbeat(
                        armed=self._native_voice_armed,
                        music_playing=music_playing,
                        allow_passive_followup=allow_passive_followup,
                    )

                    if time.time() < self._native_voice_cooldown_until and not allow_passive_followup:
                        remaining = self._native_voice_cooldown_until - time.time()
                        self._trace_native_voice_skip(f"Commit cooldown active ({remaining:.2f}s left)")
                        self._send_voice_debug(
                            status="cooldown",
                            armed=self._native_voice_armed,
                            music_playing=music_playing,
                            allow_passive_followup=allow_passive_followup,
                            skip_reason="Commit cooldown",
                        )
                        continue

                    if not self._native_voice_armed:
                        if allow_passive_followup:
                            self._trace_native_voice_skip("Passive follow-up listening")
                            self._send_voice_debug(
                                status="passive_followup",
                                armed=False,
                                music_playing=music_playing,
                                allow_passive_followup=True,
                                skip_reason="Passive follow-up listening",
                            )
                        else:
                            self._trace_native_voice_skip("Waiting for wake word")
                            self._send_voice_debug(
                                status="waiting_for_wake_word",
                                armed=False,
                                music_playing=music_playing,
                                allow_passive_followup=False,
                                skip_reason="Waiting for wake word",
                            )

                    frame_energy = float(np.mean(np.abs(audio.astype(np.float32))) / 32768.0)
                    speech_probability = None
                    if speech_detector is not None:
                        try:
                            speech_probability = float(speech_detector.predict(audio, frame_size=640))
                        except Exception as e:
                            print(f"⚠️ [VOICE] Speech detector failed; using energy fallback: {e}", flush=True)
                            speech_detector = None
                    is_speech_frame, is_start_speech_frame = self._native_speech_flags(frame_energy, speech_probability)

                    if not self._native_voice_armed and not allow_passive_followup:
                        self._native_pre_roll_audio.append(raw_audio)
                        self._update_background_energy(frame_energy, is_speech_frame)
                        if not self._music_blocks_clap_trigger(music_playing) and self._detect_clap_trigger(frame_energy):
                            print("👏 [VOICE] Clap detected — activating assistant", flush=True)
                            self._send_voice_debug(
                                status="clap_detected",
                                armed=False,
                                music_playing=music_playing,
                                allow_passive_followup=False,
                                skip_reason="Clap trigger detected",
                            )
                            self._trigger_activation_sequence("clap")
                            self._native_last_frame_energy = frame_energy
                            continue

                        try:
                            wake_model.predict(audio)
                        except Exception as e:
                            print(f"⚠️  [VOICE] Wake prediction failed: {e}", flush=True)
                            self._native_last_frame_energy = frame_energy
                            time.sleep(0.1)
                            continue

                        wake_scores: list[tuple[str, float]] = []
                        for model_name, prediction_buffer in wake_model.prediction_buffer.items():
                            if "jarvis" not in model_name.lower():
                                continue
                            try:
                                scores = list(prediction_buffer)
                                curr_score = float(scores[-1]) if scores else 0.0
                                wake_scores.append((model_name, curr_score))
                            except Exception:
                                continue

                        best_model, best_score = max(wake_scores, key=lambda item: item[1], default=("", 0.0))
                        if best_model and best_score >= activation_threshold:
                            print(f"🟢 [VOICE] Wake word detected: {best_model}={best_score:.2f} — activating assistant", flush=True)
                            self._send_voice_debug(
                                status="wake_word_detected",
                                armed=False,
                                music_playing=music_playing,
                                allow_passive_followup=False,
                                skip_reason="Wake word trigger detected",
                            )
                            # Preserve "Hey Jarvis, <command>" in one breath.
                            # A greeting here used to mute and discard the command.
                            self._native_voice_armed = True
                            self._native_recording_has_speech = True
                            self._native_recording_started_at = time.time()
                            self._native_voice_last_activity = time.time()
                            self._native_listening_window_until = time.time() + listen_window_seconds
                            self._recording_audio_buffer = list(self._native_pre_roll_audio)
                            self._audio_chunk_count = len(self._recording_audio_buffer)
                            self._total_audio_sent = sum(map(len, self._recording_audio_buffer))
                            self._native_pre_roll_audio.clear()
                            self._start_input_stream(self._recording_audio_buffer)
                            wake_model.reset()
                            if self.bridge:
                                self.bridge.set_recording_state(True)
                            self._set_voice_status("connected", "Wake word detected — listening for your request")
                            self._native_last_frame_energy = frame_energy
                            continue

                        self._native_last_frame_energy = frame_energy
                        continue

                    if not self._native_voice_armed and allow_passive_followup:
                        self._native_pre_roll_audio.append(raw_audio)

                        if is_start_speech_frame:
                            self._native_voice_last_activity = time.time()
                            self._native_speech_streak += 1
                        elif is_speech_frame:
                            self._update_background_energy(frame_energy, is_speech_frame)
                            self._native_speech_streak = max(0, self._native_speech_streak - 1)
                        else:
                            self._update_background_energy(frame_energy, is_speech_frame)
                            self._native_speech_streak = 0

                        if self._native_speech_streak >= speech_frames_required:
                            self._native_voice_armed = True
                            self._native_voice_last_activity = time.time()
                            self._native_recording_started_at = time.time()
                            self._native_recording_has_speech = True
                            self._recording_audio_buffer = list(self._native_pre_roll_audio)
                            self._audio_chunk_count = len(self._recording_audio_buffer)
                            self._total_audio_sent = sum(len(chunk) for chunk in self._recording_audio_buffer)
                            self._native_pre_roll_audio.clear()
                            self._start_input_stream(self._recording_audio_buffer)
                            print("🟡 [VOICE] Speech detected — starting native recording", flush=True)
                            self._set_voice_status("connected", "Listening — speak your command")
                            if self.bridge:
                                self.bridge.set_recording_state(True)

                        continue

                    if is_speech_frame:
                        self._native_voice_last_activity = time.time()
                        self._native_recording_has_speech = True
                    else:
                        self._update_background_energy(frame_energy, is_speech_frame)

                    if self.bridge and self.bridge.is_recording:
                        self._on_input_audio(raw_audio)

                    recording_duration = time.time() - self._native_recording_started_at
                    silence_timeout = self._native_silence_timeout(recording_duration)
                    silence_duration = time.time() - self._native_voice_last_activity

                    if recording_duration >= MAX_RECORDING_SECONDS or (recording_duration >= min_recording_duration and silence_duration >= silence_timeout):
                        if not self._native_recording_has_speech:
                            print("🛑 [VOICE] Silence detected without confirmed speech — discarding native buffer", flush=True)
                            if self.bridge:
                                self.bridge.set_recording_state(False)
                            self._native_voice_armed = False
                            self._native_voice_cooldown_until = time.time() + 0.5
                            self._native_listening_window_until = time.time() + listen_window_seconds
                            self._native_pre_roll_audio.clear()
                            self._native_speech_streak = 0
                            self._recording_audio_buffer = []
                            continue

                        print(f"🛑 [VOICE] Silence detected (energy={frame_energy:.4f}, silence={silence_duration:.1f}s) — committing native recording", flush=True)
                        if self.bridge:
                            self.bridge.set_recording_state(False)
                        if self._recording_audio_buffer:
                            self._on_commit_audio()
                        self._native_voice_armed = False
                        self._native_voice_cooldown_until = time.time() + 0.5
                        self._native_listening_window_until = time.time() + listen_window_seconds
                        self._native_pre_roll_audio.clear()
                        self._native_speech_streak = 0
                        print("🟡 [VOICE] Listening window extended — next 5 min no wake word needed", flush=True)
                        self._set_voice_status("connected", "Listening window active — speak your command")

                    self._native_last_frame_energy = frame_energy

                except Exception as e:
                    print(f"⚠️  [VOICE] Native iteration error: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
                    time.sleep(0.2)
                    continue

        except Exception as e:
            print(f"💥 [VOICE] Native wake loop crashed: {e}", flush=True)
            self._set_voice_status("error", "Wake word listener crashed")
        finally:
            self._update_music_listening_volume(False, False)
            self._native_voice_armed = False
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            try:
                if p is not None:
                    p.terminate()
            except Exception:
                pass
            self._set_voice_status("connected", "Voice wake stopped")
        
    def start(self):
        """Start the application."""
        print("=" * 60)
        print("🤖 J.A.R.V.I.S. WebSocket Edition")
        print("=" * 60)
        
        self.bridge = create_bridge(
            on_transcript=self._on_transcript,
            on_audio=self._on_input_audio,
            on_commit=self._on_commit_audio,
            on_recording_start=self._on_recording_start,
            on_recording_cancel=self._on_recording_cancel,
            on_mail_confirmation=self.confirm_mail_draft,
            host="localhost",
            port=8000
        )

        self._start_session()
        
        import time
        time.sleep(0.5)

        self._start_native_voice_listener()
        self._start_reminder_poller()

        self._start_speaker_verifier_warmup()

        self.audio_thread = threading.Thread(target=self._audio_player_thread, daemon=True)
        self.audio_thread.start()
        
        print("\n✅ JARVIS is running!")
        print("🌐 Open http://localhost:5173 in your browser")
        print("\nPress Ctrl+C to stop")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\n👋 Shutting down...")
            self.stop()
            
    def stop(self):
        """Stop the application."""
        self._stop_native_voice_listener()
        self._audio_stop.set()
        self._update_music_listening_volume(False, False)
        self._stop_reminder_poller()
        if self.bridge:
            self.bridge.stop()
        if self.session and self.event_loop:
            future = asyncio.run_coroutine_threadsafe(
                self._close_voice(),
                self.event_loop
            )
            try:
                future.result(timeout=5)
            except:
                pass

    async def _close_voice(self):
        from app.tools.memory import stop_memory_writer
        await stop_memory_writer()
        await self._input_stream.close()
        await self.session.close()
                
    def _start_session(self):
        """Start Realtime API session in background thread."""
        self.session_thread = threading.Thread(target=self._run_session, daemon=True)
        self.session_thread.start()
        
    def _run_session(self):
        """Run the asyncio event loop for Realtime session."""
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)
        
        try:
            self.event_loop.create_task(self._connect_session())
            self.event_loop.run_forever()
        except Exception as e:
            print(f"X Session error: {e}")
            import traceback
            traceback.print_exc()
            
    async def _connect_session(self):
        """Connect to Realtime API."""
        try:
            if self.session is None:
                self.session = RealtimeSession(
                    on_transcript=self._on_transcript,
                    on_audio=self._on_audio,
                    on_status=self._on_status,
                    on_speaking=self._on_speaking,
                    on_mail_draft=self._on_mail_draft,
                    on_response_start=lambda response_id: self.bridge.start_assistant_message(response_id) if self.bridge else None,
                )
            if not await self.session._ensure_connected():
                raise ConnectionError("Realtime voice unavailable")
            
            if self.bridge:
                self.bridge.send_status("connected", "J.A.R.V.I.S. SYSTEM ONLINE")

            self._drain_pending_voice_texts()
            self._flush_pending_recording()
            
            print("🔌 Connected to OpenAI Realtime API")
            print("🛠️  Tools registered:", len(self.session.tools))

            try:
                from app.tools.music_library import ensure_loaded
                asyncio.create_task(ensure_loaded())
            except Exception as e:
                print(f"⚠️  Could not schedule music library pre-warm: {e}")

            while not self._audio_stop.is_set():
                await asyncio.sleep(60)
                
        except Exception as e:
            print(f"X Connection error: {e}")
            if self.bridge:
                self.bridge.send_status("error", str(e))
            if not self._audio_stop.is_set():
                # Keep capture/control scheduling alive while voice reconnects.
                asyncio.get_running_loop().call_later(
                    3.0, lambda: asyncio.create_task(self._connect_session())
                )

    def _drain_pending_voice_texts(self) -> None:
        """Send any speech captured before the realtime session was ready."""
        if not self.session or not self.event_loop:
            return

        drained = 0
        while not self._pending_voice_texts.empty():
            try:
                text = self._pending_voice_texts.get_nowait()
            except queue.Empty:
                break

            drained += 1
            print(f"📨 [VOICE] Flushing queued speech: {text}", flush=True)
            self._send_text_to_session(text)

        if drained:
            print(f"✅ [VOICE] Flushed {drained} queued utterance(s)", flush=True)

    def _flush_pending_recording(self) -> None:
        """Commit any buffered native recording once the session is available."""
        if not self.session or not self.event_loop or not self._recording_audio_buffer:
            return

        print(f"📨 [VOICE] Flushing pending native recording ({len(self._recording_audio_buffer)} chunk(s))", flush=True)
        self._on_commit_audio()


    @staticmethod
    def _infer_recipient_from_transcript(text: str) -> str:
        email_match = re.search(r'\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b', text)
        if email_match:
            return f"{email_match.group(1)}@{email_match.group(2)}"

        spaced_email_match = re.search(
            r'\b((?:[A-Za-z0-9]\s+)+[A-Za-z0-9](?:\s*\.\s*[A-Za-z0-9]+)?)\s+(?:at|@)\s+([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b',
            text,
            re.IGNORECASE,
        )
        if spaced_email_match:
            local_part = re.sub(r'\s+', '', spaced_email_match.group(1))
            return f"{local_part}@{spaced_email_match.group(2).lower()}"

        gmail_match = re.search(r'\b([A-Za-z0-9._%+-]+)\.?gmail\.com\b', text, re.IGNORECASE)
        if gmail_match:
            return f"{gmail_match.group(1)}@gmail.com"

        at_gmail_match = re.search(r'\b([A-Za-z0-9._%+-]+)\s+(?:at|@)\s+gmail\.com\b', text, re.IGNORECASE)
        if at_gmail_match:
            return f"{at_gmail_match.group(1)}@gmail.com"

        return "recipient not captured"

    def _parse_mail_draft_from_transcript(self, assistant_text: str) -> dict | None:
        normalized_text = assistant_text.lower()
        if "subject" not in normalized_text or "body" not in normalized_text:
            return None

        if not re.search(
            r'(shall i send it\?|would you like me to send|does this look correct\?|would you like to adjust|would you like me to adjust|sound good\?|let me know if you\'d like to adjust)',
            assistant_text,
            re.IGNORECASE,
        ):
            return None

        subject_match = re.search(
            r'(?:the\s+)?subject(?:\s+(?:will\s+(?:be|say)|is|should\s+be|will\s+be|say)|:\s*)\s*([\s\S]*?)(?:\n\s*(?:and\s+)?(?:the\s+)?body\b|\n\s*$)',
            assistant_text,
            re.IGNORECASE,
        )
        if not subject_match:
            subject_match = re.search(r'Subject:\s*([\s\S]*?)(?:\n\s*Body:|\n\s*$)', assistant_text, re.IGNORECASE)

        body_match = re.search(
            r'(?:the\s+)?body(?:\s+(?:will\s+(?:say|be)|is|should\s+(?:say|be)|say|be)|:\s*)\s*([\s\S]*?)(?:\n\s*\n(?:Shall I send it\?|Would you like me to send|Does this look correct\?|Would you like to adjust|Would you like me to adjust|Sound good\?|Let me know if you\'d like to adjust)|$)',
            assistant_text,
            re.IGNORECASE,
        )

        if not subject_match or not body_match:
            return None

        subject = " ".join(line.strip() for line in subject_match.group(1).splitlines()).strip(" \"\'“”.,;:")
        body = "\n".join(line.strip() for line in body_match.group(1).splitlines()).strip(" \"\'“”.,;:")

        if not subject or not body:
            return None

        return {
            "account": "gmail",
            "to": self._infer_recipient_from_transcript(self._last_user_transcript),
            "subject": subject,
            "body": body,
            "rawText": assistant_text,
        }

    def _parse_mail_draft_from_user_request(self, user_text: str) -> dict | None:
        normalized_text = user_text.lower()
        if "email" not in normalized_text or "subject" not in normalized_text or "body" not in normalized_text:
            return None

        subject_match = re.search(
            r'(?:subject(?:\s+write|\s+is|\s+to be|\s+called)?\s*[:]?|in the subject\s+write\s*|write the subject\s*)'
            r'([\s\S]*?)(?:\s+(?:and\s+)?(?:in the body|body\s+write|body:)|$)',
            user_text,
            re.IGNORECASE,
        )
        body_match = re.search(
            r'(?:in the body\s+write\s*|body\s+write\s*|body:\s*|write the body\s*)'
            r'([\s\S]*?)(?:$)',
            user_text,
            re.IGNORECASE,
        )

        if not subject_match or not body_match:
            return None

        subject = " ".join(line.strip() for line in subject_match.group(1).splitlines()).strip(" ,.;:")
        body = " ".join(line.strip() for line in body_match.group(1).splitlines()).strip()

        if not subject or not body:
            return None

        return {
            "account": "gmail",
            "to": self._infer_recipient_from_transcript(user_text),
            "subject": subject,
            "body": body,
            "rawText": user_text,
        }
            
    def _on_transcript(self, role: str, text: str):
        """Handle transcript from the Realtime API.

        The user transcript is the orchestrator's input - the orchestrator is
        the single brain. Assistant transcripts originate from ``speak`` and are
        only forwarded to the UI.
        """
        if role == "user":
            print(f"[{role}] {text}")
            self._last_user_transcript = text
            if self.bridge:
                self.bridge.send_transcript(role, text)
            return

        if self.bridge:
            self.bridge.send_transcript(role, text)

    def _dispatch_orchestrator_turn(self, text: str) -> None:
        """Schedule the orchestrator to think about one user utterance."""
        cleaned = (text or "").strip()
        if not cleaned or not self.event_loop:
            return
        with self._turn_lock:
            if self._orchestrator_turn_in_progress:
                if len(self._pending_turns) < 4:
                    self._pending_turns.append(cleaned)
                    if self.bridge:
                        self.bridge.send_status("connected", "Request queued — I'll answer it next")
                elif self.bridge:
                    self.bridge.send_status("connected", "Request queue full — please wait for my reply")
                return
            self._orchestrator_turn_in_progress = True
        future = asyncio.run_coroutine_threadsafe(
            self._run_orchestrator_turn(cleaned), self.event_loop
        )

        def _release(done):
            try:
                done.result()
            except Exception as e:
                print(f"⚠️ [ORCH] Turn failed: {e}", flush=True)
            with self._turn_lock:
                self._orchestrator_turn_in_progress = False
                pending = self._pending_turns.popleft() if self._pending_turns else None
                # Reserve the next turn before releasing the lock.
                if pending:
                    self._orchestrator_turn_in_progress = True
            if pending:
                next_future = asyncio.run_coroutine_threadsafe(
                    self._run_orchestrator_turn(pending), self.event_loop
                )
                next_future.add_done_callback(_release)

        future.add_done_callback(_release)

    async def _run_orchestrator_turn(self, text: str) -> None:
        """Inject a typed/control request into the same streamed conversation."""
        if self.session is None:
            self._on_status("error", "Voice connection is starting — please retry")
            return
        await self.session.wait_for_turn(timeout=120)
        await self.session.send_user_text(text)
        await self.session.wait_for_turn(timeout=120)

    def _on_orchestrator_event(self, kind: str, payload: dict) -> None:
        """Surface orchestrator side-effects (mail drafts, status) to the UI."""
        if kind == "mail_draft":
            self._last_mail_draft_raw_text = payload.get("rawText", "")
            self._mail_draft_pending = True
            if self.bridge:
                self.bridge.send_mail_draft(payload)
        elif kind == "status":
            message = payload.get("message")
            if message and self.bridge:
                self.bridge.send_status("connected", message)

    def _on_status(self, state: str, message: str):
        """Handle status updates from the realtime session."""
        print(f"[status] {state}: {message}")

        if self.bridge:
            self.bridge.send_status(state, message)

    def _on_speaking(self, is_speaking: bool):
        """Handle speaking-state updates from the realtime session."""
        self._speech_active = is_speaking
        self._publish_speaking_state()

    def _set_playback_active(self, active: bool) -> None:
        self._playback_active = active
        self._publish_speaking_state()

    def _publish_speaking_state(self) -> None:
        is_speaking = self._speech_active or self._playback_active
        if self.bridge:
            self.bridge.set_speaking_state(is_speaking)
        if not is_speaking:
            self._jarvis_last_output_at = time.time()
            self._native_mic_resume_at = time.time() + NATIVE_MIC_RESUME_DELAY_SECONDS
            self._native_listening_window_until = time.time() + 300.0
        else:
            # The speaking flag owns the mute. Never leave an infinite second
            # gate behind when playback is interrupted or fails.
            self._native_mic_resume_at = 0.0

    def _on_mail_draft(self, draft: dict):
        """Handle structured mail drafts from the realtime session."""
        self._mail_draft_pending = not draft.get('cleared', False)
        self._last_mail_draft_raw_text = draft.get('rawText', '')

        if self.bridge:
            self.bridge.send_mail_draft(draft)
            
    def _on_audio(self, audio_bytes: bytes):
        """Handle audio OUTPUT from Realtime API (JARVIS speaking)."""
        if self.bridge and self.bridge.is_recording:
            self._clear_audio_queue()
            return

        self._set_playback_active(True)
        self.audio_queue.put(audio_bytes)
        self._jarvis_last_output_at = time.time()
        
    def _on_input_audio(self, audio_bytes: bytes):
        """Collect 16 kHz PCM for the current recording only."""
        if not (self.bridge and self.bridge.is_recording):
            return
        if self._total_audio_sent + len(audio_bytes) > int(MAX_RECORDING_SECONDS * 16000 * 2):
            self.bridge.set_recording_state(False)
            self._native_voice_armed = False
            self._on_commit_audio()
            return
        self._recording_audio_buffer.append(audio_bytes)
        self._audio_chunk_count += 1
        self._total_audio_sent += len(audio_bytes)
        self._offer_input('audio', audio_bytes)

    @staticmethod
    def _pcm16_to_wav(pcm16_bytes: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
        """Wrap raw PCM16 bytes in a valid WAV container for Whisper."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm16_bytes)
        return buf.getvalue()

    def _offer_input(self, kind: str, audio: bytes = b'') -> None:
        if self.event_loop is not None:
            self.event_loop.call_soon_threadsafe(self._input_stream.offer, kind, self._input_turn_id, audio)

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

    def _on_commit_audio(self):
        """Commit the already-streamed recording without blocking capture."""
        self._frontend_recording = False
        self._recording_audio_buffer = []
        self._total_audio_sent = 0
        self._audio_chunk_count = 0
        self._offer_input('end')

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
    
    def _on_recording_start(self):
        """Reset state when recording starts."""
        print("🔄 Recording started - resetting response state")
        self._frontend_recording = True
        self._native_voice_armed = False
        self._native_pre_roll_audio.clear()
        self._native_speech_streak = 0
        self._recording_audio_buffer = []
        self._audio_chunk_count = 0
        self._total_audio_sent = 0
        if self.session:
            future = asyncio.run_coroutine_threadsafe(
                self.session.interrupt_active_response(),
                self.event_loop,
            )
            try:
                future.result(timeout=0.5)
            except Exception as e:
                print(f"⚠️  Error interrupting active response: {e}")

        if self.bridge:
            if self._speaking_timer:
                self._speaking_timer.cancel()
                self._speaking_timer = None
            self._on_speaking(False)
            self._native_mic_resume_at = 0.0
            print("🔊 Speaking state cleared - ready for input")

        self._clear_audio_queue()
        self._start_input_stream()

    def _on_recording_cancel(self):
        self._offer_input('cancel')
        self._frontend_recording = False
        self._reset_native_recording_state()

    async def _send_confirmed_mail_draft(self, draft: dict):
        """Send the edited mail draft directly through the registry."""
        payload = {
            "to": (draft.get("to") or "").strip(),
            "subject": (draft.get("subject") or "").strip(),
            "body": draft.get("body") or "",
            "account": (draft.get("account") or "gmail").strip().lower(),
            "confirmed": True,
        }

        if self.session:
            try:
                await self.session.interrupt_active_response()
            except Exception as e:
                print(f"⚠️  [MAIL] Error interrupting active response: {e}")

        result = await REGISTRY.call("mail_send", payload)
        if result.get("ok"):
            print("✅ [MAIL] Draft sent successfully")
            if self.bridge:
                self.bridge.send_status("connected", "Email sent")
        else:
            error_msg = result.get("error", "Unknown mail error")
            print(f"⚠️  [MAIL] Failed to send edited draft: {error_msg}")
            if self.bridge:
                self.bridge.send_status("error", f"Email send failed: {error_msg}")

    def confirm_mail_draft(self, payload: dict | bool = True):
        """Confirm or cancel a pending mail draft from the UI."""
        if not self._mail_draft_pending:
            return
        if not self.session or not self.event_loop:
            print("⚠️  [MAIL] Session not ready for confirmation")
            return

        if isinstance(payload, dict):
            accepted = bool(payload.get("accepted", True))
            draft = payload.get("draft") if isinstance(payload.get("draft"), dict) else None
        else:
            accepted = bool(payload)
            draft = None

        self._mail_draft_pending = False
        if self.bridge:
            self.bridge.send_mail_draft({'cleared': True})

        if not accepted:
            self._last_mail_draft_raw_text = ""
            return

        if draft:
            future = asyncio.run_coroutine_threadsafe(
                self._send_confirmed_mail_draft(draft),
                self.event_loop,
            )
        else:
            future = asyncio.run_coroutine_threadsafe(
                self.session.send_user_text("yes"),
                self.event_loop,
            )

        try:
            future.result(timeout=2)
        except Exception as e:
            print(f"⚠️  [MAIL] Error sending confirmation: {e}")
        
    def _start_reminder_poller(self) -> None:
        """Start the background reminder poller thread."""
        if self._reminder_poller_thread and self._reminder_poller_thread.is_alive():
            return
        self._reminder_poller_stop.clear()
        self._reminder_poller_thread = threading.Thread(target=self._reminder_poller_loop, daemon=True)
        self._reminder_poller_thread.start()
        print("⏰ Reminder poller started", flush=True)

    def _stop_reminder_poller(self) -> None:
        """Signal the reminder poller to stop."""
        self._reminder_poller_stop.set()

    def _reminder_poller_loop(self) -> None:
        """Background loop: check for due reminders every 10 seconds and alert the user."""
        try:
            from app.tools.reminders import _due_notes, _mark_reminded
        except Exception as e:
            print(f"⚠️  Reminder poller unavailable: {e}", flush=True)
            return

        CHECK_INTERVAL = 10.0
        DEDUP_WINDOW = 60.0  # Don't re-alert the same reminder within 60s

        while not self._reminder_poller_stop.is_set():
            try:
                due = _due_notes()
                now = time.time()
                for reminder in due:
                    rid = reminder.get("id", "")
                    text = reminder.get("text", "")
                    if not rid or not text:
                        continue
                    last_alerted = self._reminder_last_alerted.get(rid, 0)
                    if now - last_alerted < DEDUP_WINDOW:
                        continue

                    # Alert: play a soft chime if available, then speak
                    print(f"⏰ Reminder due: {text}", flush=True)
                    self._reminder_last_alerted[rid] = now
                    _mark_reminded(rid)

                    if self.bridge:
                        self.bridge.send_status("connected", f"Reminder: {text}")

                    # Speak the reminder if session is ready
                    if self.session is not None and self.event_loop is not None:
                        alert_text = f"Sir, it's time: {text}."
                        try:
                            future = asyncio.run_coroutine_threadsafe(
                                self.session.speak(alert_text),
                                self.event_loop,
                            )
                            future.result(timeout=5)
                        except Exception as e:
                            print(f"⚠️  Failed to speak reminder: {e}", flush=True)
            except Exception as e:
                print(f"⚠️  Reminder poller error: {e}", flush=True)

            # Sleep in small increments so we can exit promptly
            for _ in range(int(CHECK_INTERVAL * 2)):
                if self._reminder_poller_stop.is_set():
                    break
                time.sleep(0.5)

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
                    response_active = bool(self.session and getattr(self.session, "_response_active", False))
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


def main():
    """Main entry point."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    
    if api_key:
        masked = api_key[:10] + "..." + api_key[-4:] if len(api_key) > 14 else "***"
        print(f"🔑 API Key loaded: {masked}")
    else:
        print("X Error: OPENAI_API_KEY not set")
        print("Please set your OpenAI API key in the .env file")
        print(f"Looking for: {SCRIPT_DIR / '.env'}")
        sys.exit(1)
        
    app = JarvisWebSocketApp()
    app.start()


if __name__ == "__main__":
    main()

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
from collections import deque
import re
import time
import importlib.util
from pathlib import Path
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent.resolve()

env_path = SCRIPT_DIR / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print(f"✅ Loaded .env from {env_path}")
else:
    print(f"⚠️  Warning: .env file not found at {env_path}")

sys.path.insert(0, str(SCRIPT_DIR))

from app.core.realtime_session import RealtimeSession
from app.core.config import get_settings
from app.core.music_state import is_music_playing
from app.core.websocket_bridge import create_bridge, get_bridge
from app.runtime import REGISTRY


class JarvisWebSocketApp:
    """JARVIS voice assistant with WebSocket frontend."""
    
    def __init__(self):
        self.session: RealtimeSession = None
        self.event_loop: asyncio.AbstractEventLoop = None
        self.session_thread: threading.Thread = None
        self._native_voice_thread: threading.Thread = None
        self._native_voice_stop = threading.Event()
        self._native_voice_armed = False
        self._native_voice_last_activity = 0.0
        self._native_recording_started_at = 0.0
        self._native_voice_cooldown_until = 0.0
        self._jarvis_last_output_at = 0.0
        self._native_mic_resume_at = 0.0
        self._native_music_override_until = 0.0
        self._native_listening_window_until = 0.0
        self._native_recording_has_speech = False
        self._native_background_energy = 0.0
        self._native_pre_roll_audio: deque[bytes] = deque(maxlen=6)
        self._native_speech_streak = 0
        self._native_voice_last_status = ""
        self.pending_mail_draft = None
        self._recording_audio_buffer = []
        self._audio_chunk_count = 0
        self._total_audio_sent = 0
        self._last_user_transcript = ""
        self._last_mail_draft_raw_text = ""
        self._mail_draft_pending = False
        self._pending_voice_texts: queue.Queue[str] = queue.Queue()
        
        self.audio_queue = queue.Queue()
        self.audio_thread: threading.Thread = None
        self.is_playing = False
        
        self.bridge = None
        
        self._speaking_timer = None

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
            }
        except Exception as e:
            print(f"⚠️  [VOICE] Failed to load voice settings: {e}")
            return {"enabled": True, "wakeWord": "Hey JARVIS", "sensitivity": 0.5}

    @staticmethod
    def _native_voice_dependencies() -> list[str]:
        required = ["openwakeword", "pyaudio"]
        missing = [name for name in required if importlib.util.find_spec(name) is None]
        return missing

    def _set_voice_status(self, state: str, message: str) -> None:
        status_key = f"{state}:{message}"
        if status_key == self._native_voice_last_status:
            return
        self._native_voice_last_status = status_key
        if self.bridge:
            self.bridge.send_status(state, message)

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
        self._native_voice_thread = threading.Thread(target=self._native_voice_loop, daemon=True)
        self._native_voice_thread.start()
        print("🎙️ Native wake-word listener starting", flush=True)

    def _stop_native_voice_listener(self) -> None:
        self._native_voice_stop.set()

    def _send_text_to_session(self, text: str) -> None:
        if not self.session or not self.event_loop:
            print(f"🕒 [VOICE] Session not ready yet, queueing speech: {text}")
            self._pending_voice_texts.put(text)
            return

        future = asyncio.run_coroutine_threadsafe(self.session.send_user_text(text), self.event_loop)
        try:
            future.result(timeout=5)
        except Exception as e:
            print(f"⚠️  [VOICE] Error forwarding native speech to session: {e}")

    def _strip_wake_word(self, transcript: str, wake_word: str) -> str:
        transcript_norm = self._normalize_wake_word(transcript)
        wake_norm = self._normalize_wake_word(wake_word)
        if not transcript_norm:
            return ""

        candidates = [wake_norm, "hey jarvis", "jarvis"]
        cleaned = transcript_norm
        for candidate in candidates:
            if cleaned.startswith(candidate):
                cleaned = cleaned[len(candidate):].strip()
                break
        return cleaned

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
        wake_norm = self._normalize_wake_word(wake_word)

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
            model_names = list(wake_model.models.keys())
            print(f"🧠 [VOICE] openWakeWord models loaded: {', '.join(model_names)}", flush=True)
        except Exception as e:
            print(f"⚠️  [VOICE] Failed to load openWakeWord model: {e}", flush=True)
            self._set_voice_status("error", "Wake word model unavailable")
            return

        p = None
        stream = None
        chunk_size = 1280
        speech_threshold_floor = 0.0035
        speech_threshold_multiplier = 3.5
        speech_start_threshold_floor = 0.008
        speech_start_threshold_multiplier = 5.0
        silence_timeout = 1.2
        min_recording_duration = 0.5
        listen_window_seconds = 300.0  # 5 minutes follow-up window
        speech_frames_required = 3

        try:
            p = pyaudio.PyAudio()
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=chunk_size,
            )
            print("🎙️ [VOICE] Microphone stream opened (16kHz mono)", flush=True)
        except Exception as e:
            print(f"⚠️  [VOICE] No microphone available: {e}", flush=True)
            self._set_voice_status("error", "Microphone unavailable")
            if p is not None:
                p.terminate()
            return

        self._set_voice_status("connected", f'Wake word armed — say "{wake_word}"')

        try:
            while not self._native_voice_stop.is_set():
                now = time.time()
                music_playing = is_music_playing()
                music_override_active = now < self._native_music_override_until
                music_blocks_passive = music_playing and not music_override_active

                if self.bridge and self.bridge.is_speaking:
                    if self._native_voice_armed:
                        print("🔇 [VOICE] JARVIS speaking — aborting recording", flush=True)
                        self._recording_audio_buffer = []
                        self._audio_chunk_count = 0
                        self._total_audio_sent = 0
                        self.bridge.set_recording_state(False)
                        self._native_voice_armed = False
                    time.sleep(0.05)
                    continue

                if music_blocks_passive:
                    print("🔇 [VOICE] Music is playing — passive follow-up paused", flush=True)
                    if self._native_voice_armed:
                        print("🔇 [VOICE] Music is playing — aborting recording", flush=True)
                        self._recording_audio_buffer = []
                        self._audio_chunk_count = 0
                        self._total_audio_sent = 0
                        if self.bridge:
                            self.bridge.set_recording_state(False)
                        self._native_voice_armed = False

                if time.time() < self._native_mic_resume_at:
                    time.sleep(0.05)
                    continue

                try:
                    raw_audio = stream.read(chunk_size, exception_on_overflow=False)
                except Exception as e:
                    print(f"⚠️  [VOICE] Mic read error: {e}", flush=True)
                    time.sleep(0.1)
                    continue

                try:
                    audio = np.frombuffer(raw_audio, dtype=np.int16)
                    if audio.size == 0:
                        continue

                    in_listening_window = time.time() < self._native_listening_window_until
                    allow_passive_followup = in_listening_window and not music_blocks_passive

                    if time.time() < self._native_voice_cooldown_until and not allow_passive_followup:
                        continue

                    seconds_since_output = time.time() - self._jarvis_last_output_at
                    if seconds_since_output < 1.0:
                        continue

                    frame_energy = float(np.mean(np.abs(audio.astype(np.float32))) / 32768.0)
                    dynamic_threshold = max(
                        speech_threshold_floor,
                        self._native_background_energy * speech_threshold_multiplier,
                    )
                    speech_start_threshold = max(
                        speech_start_threshold_floor,
                        self._native_background_energy * speech_start_threshold_multiplier,
                        dynamic_threshold * 1.5,
                    )
                    is_speech_frame = frame_energy >= dynamic_threshold
                    is_start_speech_frame = frame_energy >= speech_start_threshold

                    if not self._native_voice_armed and not allow_passive_followup:
                        try:
                            wake_model.predict(audio)
                        except Exception as e:
                            print(f"⚠️  [VOICE] Wake prediction failed: {e}", flush=True)
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
                            self._native_voice_last_activity = time.time()
                            self._native_recording_started_at = time.time()
                            self._native_recording_has_speech = False
                            self._recording_audio_buffer = []
                            self._audio_chunk_count = 0
                            self._total_audio_sent = 0
                            self._native_listening_window_until = time.time() + listen_window_seconds
                            self._native_pre_roll_audio.clear()
                            if music_playing:
                                self._native_music_override_until = time.time() + 8.0
                                print("🔓 [VOICE] Wake word heard during music — enabling temporary mic override", flush=True)
                            print(f"🟢 [VOICE] Wake word detected: {best_model}={best_score:.2f} — listening window open for 5 min", flush=True)
                            self._set_voice_status("connected", "Wake word detected — listening for your request (5 min window)")
                            continue

                        continue

                    if not self._native_voice_armed and allow_passive_followup:
                        self._native_pre_roll_audio.append(raw_audio)

                        if is_start_speech_frame:
                            self._native_voice_last_activity = time.time()
                            self._native_background_energy = (
                                self._native_background_energy * 0.99
                            ) + (frame_energy * 0.01)
                            self._native_speech_streak += 1
                        elif is_speech_frame:
                            self._native_background_energy = (
                                self._native_background_energy * 0.995
                            ) + (frame_energy * 0.005)
                            self._native_speech_streak = max(0, self._native_speech_streak - 1)
                        else:
                            self._native_background_energy = (
                                self._native_background_energy * 0.995
                            ) + (frame_energy * 0.005)
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
                            print("🟡 [VOICE] Speech detected — starting native recording", flush=True)
                            self._set_voice_status("connected", "Listening — speak your command")
                            if self.bridge:
                                self.bridge.set_recording_state(True)

                        continue

                    if is_speech_frame:
                        self._native_voice_last_activity = time.time()
                        self._native_recording_has_speech = True
                        self._native_background_energy = (
                            self._native_background_energy * 0.99
                        ) + (frame_energy * 0.01)
                    else:
                        self._native_background_energy = (
                            self._native_background_energy * 0.995
                        ) + (frame_energy * 0.005)

                    if self.bridge and self.bridge.is_recording:
                        self._on_input_audio(raw_audio)

                    recording_duration = time.time() - self._native_recording_started_at
                    silence_duration = time.time() - self._native_voice_last_activity

                    if recording_duration >= min_recording_duration and silence_duration >= silence_timeout:
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
                        if self._recording_audio_buffer:
                            self._on_commit_audio()
                        if self.bridge:
                            self.bridge.set_recording_state(False)
                        self._native_voice_armed = False
                        self._native_voice_cooldown_until = time.time() + 0.5
                        self._native_listening_window_until = time.time() + listen_window_seconds
                        self._native_pre_roll_audio.clear()
                        self._native_speech_streak = 0
                        print("🟡 [VOICE] Listening window extended — next 5 min no wake word needed", flush=True)
                        self._set_voice_status("connected", "Listening window active — speak your command")

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
            on_mail_confirmation=self.confirm_mail_draft,
            host="localhost",
            port=8000
        )
        
        import time
        time.sleep(0.5)

        self._start_native_voice_listener()
        
        self._start_session()

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
        if self.bridge:
            self.bridge.stop()
        if self.session and self.event_loop:
            future = asyncio.run_coroutine_threadsafe(
                self.session.close(),
                self.event_loop
            )
            try:
                future.result(timeout=5)
            except:
                pass
                
    def _start_session(self):
        """Start Realtime API session in background thread."""
        self.session_thread = threading.Thread(target=self._run_session, daemon=True)
        self.session_thread.start()
        
    def _run_session(self):
        """Run the asyncio event loop for Realtime session."""
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)
        
        try:
            self.event_loop.run_until_complete(self._connect_session())
        except Exception as e:
            print(f"X Session error: {e}")
            import traceback
            traceback.print_exc()
            
    async def _connect_session(self):
        """Connect to Realtime API."""
        try:
            self.session = RealtimeSession(
                on_transcript=self._on_transcript,
                on_audio=self._on_audio,
                on_status=self._on_status,
                on_speaking=self._on_speaking,
                on_mail_draft=self._on_mail_draft,
            )
            
            await self.session.connect()
            await self.session.configure()
            
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

            while True:
                await asyncio.sleep(1)
                
        except Exception as e:
            print(f"X Connection error: {e}")
            if self.bridge:
                self.bridge.send_status("error", str(e))

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
            future = asyncio.run_coroutine_threadsafe(self.session.send_user_text(text), self.event_loop)
            try:
                future.result(timeout=5)
            except Exception as e:
                print(f"⚠️  [VOICE] Error flushing queued speech: {e}", flush=True)

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
        """Handle transcript from Realtime API."""
        if role == "user":
            print(f"[{role}] {text}")

        if role == "user":
            self._last_user_transcript = text
            if not self._mail_draft_pending:
                draft = self._parse_mail_draft_from_user_request(text)
                if draft and draft["rawText"] != self._last_mail_draft_raw_text:
                    self._last_mail_draft_raw_text = draft["rawText"]
                    self._mail_draft_pending = True
                    if self.bridge:
                        self.bridge.send_mail_draft(draft)
        elif role == "assistant" and self.bridge:
            if self._mail_draft_pending:
                self.bridge.send_transcript(role, text)
                return
            draft = self._parse_mail_draft_from_transcript(text)
            if draft and draft["rawText"] != self._last_mail_draft_raw_text:
                self._last_mail_draft_raw_text = draft["rawText"]
                self._mail_draft_pending = True
                self.bridge.send_mail_draft(draft)
        
        if self.bridge:
            self.bridge.send_transcript(role, text)

    def _on_status(self, state: str, message: str):
        """Handle status updates from the realtime session."""
        print(f"[status] {state}: {message}")

        if self.bridge:
            self.bridge.send_status(state, message)

    def _on_speaking(self, is_speaking: bool):
        """Handle speaking-state updates from the realtime session."""
        if self.bridge:
            self.bridge.set_speaking_state(is_speaking)
        if not is_speaking:
            self._jarvis_last_output_at = time.time()
            self._native_mic_resume_at = time.time() + 1.0
        else:
            self._native_mic_resume_at = float("inf")

    def _on_mail_draft(self, draft: dict):
        """Handle structured mail drafts from the realtime session."""
        print("[mail_draft] preview ready")

        if self.bridge:
            self.bridge.send_mail_draft(draft)
            
    def _on_audio(self, audio_bytes: bytes):
        """Handle audio OUTPUT from Realtime API (JARVIS speaking)."""
        if self.bridge and self.bridge.is_recording:
            self._clear_audio_queue()
            return

        if self.bridge:
            if not self.bridge.is_speaking:
                self._on_speaking(True)
            
        self.audio_queue.put(audio_bytes)
        self._jarvis_last_output_at = time.time()
        
    def _on_input_audio(self, audio_bytes: bytes):
        """Handle audio INPUT from frontend (user speaking) - send to OpenAI."""
        if self.bridge and self.bridge.is_recording:
            self._recording_audio_buffer.append(audio_bytes)
            self._audio_chunk_count += 1
            if self._audio_chunk_count <= 5 or self._audio_chunk_count % 20 == 0:
                print(f"🧠 [AUDIO] Buffered chunk #{self._audio_chunk_count} until recording stops")
            return

        if not self.session or not self.event_loop:
            print("⚠️  [AUDIO] Session not ready, dropping audio")
            return

        if self.bridge and self.bridge.is_speaking:
            print(f"🔇 [AUDIO] JARVIS speaking, dropping {len(audio_bytes)} bytes")
            return
            
        if not hasattr(self, '_total_audio_sent'):
            self._total_audio_sent = 0
            self._audio_chunk_count = 0
            print(f"🎵 [AUDIO] First chunk received: {len(audio_bytes)} bytes")
        
        self._total_audio_sent += len(audio_bytes)
        self._audio_chunk_count += 1
        
        if self._audio_chunk_count <= 5 or self._audio_chunk_count % 20 == 0:
            print(f"📥 [AUDIO] Chunk #{self._audio_chunk_count}: {len(audio_bytes)} bytes (total: {self._total_audio_sent})")

        if self.bridge and self.bridge.is_recording:
            self._recording_audio_buffer.append(audio_bytes)
            if self._audio_chunk_count <= 5 or self._audio_chunk_count % 20 == 0:
                print(f"🧠 [AUDIO] Buffered chunk #{self._audio_chunk_count} until recording stops")
            return
            
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.session.append_audio(audio_bytes),
                self.event_loop
            )
            future.result(timeout=0.5)
        except Exception as e:
            print(f"X [AUDIO] Error sending chunk #{self._audio_chunk_count}: {e}")

    async def _commit_buffered_audio(self, buffered_chunks):
        for chunk in buffered_chunks:
            await self.session.append_audio(chunk)
        await self.session.commit_audio()
            
    def _on_commit_audio(self):
        """Commit audio buffer when user stops recording."""
        if self.session and self.event_loop:
            total_sent = getattr(self, '_total_audio_sent', 0)
            chunk_count = getattr(self, '_audio_chunk_count', 0)
            print(f"🎯 Preparing to commit... received {chunk_count} chunks, {total_sent} bytes")
            
            import time
            time.sleep(0.2)
            
            new_count = getattr(self, '_audio_chunk_count', 0)
            if new_count > chunk_count:
                print(f"📥 Received {new_count - chunk_count} more chunks during wait")
            
            print(f"🎯 Committing audio buffer... (total: {new_count} chunks)")

            buffered_chunks = list(self._recording_audio_buffer)
            self._recording_audio_buffer = []
            if not buffered_chunks:
                print("⚠️  No buffered audio to commit")
                self._total_audio_sent = 0
                self._audio_chunk_count = 0
                return

            future = asyncio.run_coroutine_threadsafe(
                self._commit_buffered_audio(buffered_chunks),
                self.event_loop
            )
            try:
                future.result(timeout=5)
            except Exception as e:
                print(f"⚠️  Error committing audio: {e}")
            
            self._total_audio_sent = 0
            self._audio_chunk_count = 0

    def _clear_audio_queue(self):
        """Drop any queued assistant audio when the user interrupts."""
        cleared = 0
        while True:
            try:
                self.audio_queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break

        if cleared:
            print(f"🧹 Cleared {cleared} queued audio chunk(s)")
    
    def _on_recording_start(self):
        """Reset state when recording starts."""
        print("🔄 Recording started - resetting response state")
        self._recording_audio_buffer = []
        self._last_mail_draft_raw_text = ""
        self._mail_draft_pending = False
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
            self.bridge.set_speaking_state(False)
            print("🔊 Speaking state cleared - ready for input")

        self._clear_audio_queue()

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
        
    def _audio_player_thread(self):
        """Play audio from queue with buffering for smooth playback."""
        try:
            import pyaudio
            import time
            
            p = pyaudio.PyAudio()
            
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=24000,
                output=True,
                frames_per_buffer=2048
            )
            
            print("🔊 Audio output ready")
            
            audio_buffer = bytearray()
            min_buffer_size = 4800
            idle_clear_seconds = 1.0
            
            while True:
                try:
                    audio_chunk = self.audio_queue.get(timeout=0.05)
                    audio_buffer.extend(audio_chunk)
                    
                    while len(audio_buffer) >= min_buffer_size:
                        write_size = min(len(audio_buffer), 4800)
                        stream.write(bytes(audio_buffer[:write_size]))
                        audio_buffer = audio_buffer[write_size:]
                        
                except queue.Empty:
                    if len(audio_buffer) > 0:
                        stream.write(bytes(audio_buffer))
                        audio_buffer = bytearray()
                    if (
                        self.bridge
                        and self.bridge.is_speaking
                        and len(audio_buffer) == 0
                        and (time.time() - self._jarvis_last_output_at) >= idle_clear_seconds
                    ):
                        self._on_speaking(False)
                    continue
                    
        except Exception as e:
            print(f"X Audio error: {e}")
            import traceback
            traceback.print_exc()


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

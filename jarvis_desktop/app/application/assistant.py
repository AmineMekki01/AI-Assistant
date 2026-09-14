"""Composition root: assemble components and own the conversation session."""
from __future__ import annotations

import asyncio
import queue
import threading
import time
from collections import deque

from app.core.config import get_settings
from app.core.realtime_session import RealtimeSession
from app.core.websocket_bridge import create_bridge
from app.runtime import REGISTRY, load_all_capabilities
from app.voice.listener import NativeVoiceController
from app.voice.playback import AudioPlayback
from .activation import ActivationController
from .mail import MailController
from .reminders import ReminderScheduler


class AssistantApplication:
    """Assemble voice and application components without opening devices on import."""

    def __init__(self, *, settings=None, registry=None, session_factory=None, bridge_factory=None):
        self.settings = settings if settings is not None else get_settings()
        self.registry = registry if registry is not None else REGISTRY
        self.session_factory = session_factory or RealtimeSession
        self.bridge_factory = bridge_factory or create_bridge
        self.session: RealtimeSession = None
        self.event_loop: asyncio.AbstractEventLoop = None
        self.session_thread: threading.Thread = None
        self._turn_lock = threading.Lock()
        self._pending_turns: deque[str] = deque()
        self._last_user_transcript = ""
        self._pending_voice_texts: queue.Queue[str] = queue.Queue()
        self._orchestrator_turn_in_progress = False
        self.bridge = None
        self.voice = NativeVoiceController(self)
        self.audio = AudioPlayback(self)
        self.activation = ActivationController(self)
        self.mail = MailController(self)
        self.reminders = ReminderScheduler(self)

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
        self.dispatch_text(cleaned)

    def start(self):
        """Start the application."""
        print("=" * 60)
        print("🤖 J.A.R.V.I.S. WebSocket Edition")
        print("=" * 60)
        
        load_all_capabilities(self.settings.extra_capability_modules)
        self.registry.configure(disabled=self.settings.disabled_capabilities, timeout=self.settings.capability_timeout_seconds)
        self.bridge = self.bridge_factory(
            on_transcript=self._on_transcript,
            on_audio=self.voice.receive_audio,
            on_commit=self.voice.commit_recording,
            on_recording_start=self.voice.start_recording,
            on_recording_cancel=self.voice.cancel_recording,
            on_mail_confirmation=self.mail.confirm,
            host=self.settings.server_host,
            port=self.settings.websocket_port,
            api_port=self.settings.api_port
        )

        self._start_session()
        
        time.sleep(0.5)

        self.voice.start()
        self.reminders.start()

        self.voice._start_speaker_verifier_warmup()

        self.audio.audio_thread = threading.Thread(target=self.audio._audio_player_thread, daemon=True)
        self.audio.audio_thread.start()
        
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
        self.voice.stop()
        self.audio._audio_stop.set()
        self.audio._update_music_listening_volume(False, False)
        self.reminders.stop()
        if self.bridge:
            self.bridge.stop()
        if self.session and self.event_loop:
            future = asyncio.run_coroutine_threadsafe(
                self._close_voice(),
                self.event_loop
            )
            try:
                future.result(timeout=5)
            except Exception:
                pass

    async def _close_voice(self):
        from app.tools.memory import stop_memory_writer
        await stop_memory_writer()
        await self.voice._input_stream.close()
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
                self.session = self.session_factory(
                    registry=self.registry,
                    on_transcript=self._on_transcript,
                    on_audio=self.audio.receive_audio,
                    on_status=self._on_status,
                    on_speaking=self.audio.set_speaking,
                    on_mail_draft=self.mail.receive_draft,
                    on_response_start=lambda response_id: self.bridge.start_assistant_message(response_id) if self.bridge else None,
                )
            if not await self.session._ensure_connected():
                raise ConnectionError("Realtime voice unavailable")
            
            if self.bridge:
                self.bridge.send_status("connected", "J.A.R.V.I.S. SYSTEM ONLINE")

            self._drain_pending_voice_texts()
            self.voice._flush_pending_recording()
            
            print("🔌 Connected to OpenAI Realtime API")
            print("🛠️  Tools registered:", len(self.session.tools))

            try:
                from app.tools.music_library import ensure_loaded
                asyncio.create_task(ensure_loaded())
            except Exception as e:
                print(f"⚠️  Could not schedule music library pre-warm: {e}")

            while not self.audio._audio_stop.is_set():
                await asyncio.sleep(60)
                
        except Exception as e:
            print(f"X Connection error: {e}")
            if self.bridge:
                self.bridge.send_status("error", str(e))
            if not self.audio._audio_stop.is_set():
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

    def dispatch_text(self, text: str) -> None:
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
            self._run_text_turn(cleaned), self.event_loop
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
                    self._run_text_turn(pending), self.event_loop
                )
                next_future.add_done_callback(_release)

        future.add_done_callback(_release)

    async def _run_text_turn(self, text: str) -> None:
        """Inject a typed/control request into the same streamed conversation."""
        if self.session is None:
            self._on_status("error", "Voice connection is starting — please retry")
            return
        await self.session.wait_for_turn(timeout=120)
        await self.session.send_user_text(text)
        await self.session.wait_for_turn(timeout=120)

    def _on_status(self, state: str, message: str):
        """Handle status updates from the realtime session."""
        print(f"[status] {state}: {message}")

        if self.bridge:
            self.bridge.send_status(state, message)

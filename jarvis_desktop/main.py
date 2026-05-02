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
import re
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
from app.core.websocket_bridge import create_bridge, get_bridge
from app.runtime import REGISTRY


class JarvisWebSocketApp:
    """JARVIS voice assistant with WebSocket frontend."""
    
    def __init__(self):
        self.session: RealtimeSession = None
        self.event_loop: asyncio.AbstractEventLoop = None
        self.session_thread: threading.Thread = None
        self.pending_mail_draft = None
        self._recording_audio_buffer = []
        self._last_user_transcript = ""
        self._last_mail_draft_raw_text = ""
        self._mail_draft_pending = False
        
        self.audio_queue = queue.Queue()
        self.audio_thread: threading.Thread = None
        self.is_playing = False
        
        self.bridge = None
        
        self._speaking_timer = None
        
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

    def _on_mail_draft(self, draft: dict):
        """Handle structured mail drafts from the realtime session."""
        print("[mail_draft] preview ready")

        if self.bridge:
            self.bridge.send_mail_draft(draft)
            
    def _on_audio(self, audio_bytes: bytes):
        """Handle audio OUTPUT from Realtime API (JARVIS speaking)."""
        import threading
        
        if self.bridge and self.bridge.is_recording:
            self._clear_audio_queue()
            return

        if self.bridge:
            if self._speaking_timer:
                self._speaking_timer.cancel()
                
            if not self.bridge.is_speaking:
                self.bridge.set_speaking_state(True)
            
        self.audio_queue.put(audio_bytes)
        
        duration_ms = len(audio_bytes) / 48
        
        def clear_speaking():
            if self.bridge:
                self.bridge.set_speaking_state(False)
                self._speaking_timer = None
                
        delay = max(duration_ms / 1000 + 2.0, 3.0)
        self._speaking_timer = threading.Timer(delay, clear_speaking)
        self._speaking_timer.start()
        
    def _on_input_audio(self, audio_bytes: bytes):
        """Handle audio INPUT from frontend (user speaking) - send to OpenAI."""
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

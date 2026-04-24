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


class JarvisWebSocketApp:
    """JARVIS voice assistant with WebSocket frontend."""
    
    def __init__(self):
        self.session: RealtimeSession = None
        self.event_loop: asyncio.AbstractEventLoop = None
        self.session_thread: threading.Thread = None
        
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
                on_audio=self._on_audio
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
            
    def _on_transcript(self, role: str, text: str):
        """Handle transcript from Realtime API."""
        print(f"[{role}] {text}")
        
        if self.bridge:
            self.bridge.send_transcript(role, text)
            
    def _on_audio(self, audio_bytes: bytes):
        """Handle audio OUTPUT from Realtime API (JARVIS speaking)."""
        import threading
        
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
            
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.session.append_audio(audio_bytes),
                self.event_loop
            )
            future.result(timeout=0.5)
        except Exception as e:
            print(f"X [AUDIO] Error sending chunk #{self._audio_chunk_count}: {e}")
            
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
            
            future = asyncio.run_coroutine_threadsafe(
                self.session.commit_audio(),
                self.event_loop
            )
            try:
                future.result(timeout=2)
            except Exception as e:
                print(f"⚠️  Error committing audio: {e}")
            
            self._total_audio_sent = 0
            self._audio_chunk_count = 0
    
    def _on_recording_start(self):
        """Reset state when recording starts."""
        print("🔄 Recording started - resetting response state")
        if self.session:
            self.session.reset_turn()

        if self.bridge:
            if self._speaking_timer:
                self._speaking_timer.cancel()
                self._speaking_timer = None
            self.bridge.set_speaking_state(False)
            print("🔊 Speaking state cleared - ready for input")
        
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

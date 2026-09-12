"""
WebSocket Bridge - Connects React Frontend to OpenAI Realtime API
"""

import base64
import asyncio
import json
import threading
import time
from typing import Any, Callable, Optional

import numpy as np
from aiohttp import web
import aiohttp_cors
import websockets

from ..api.routes import register_routes


class WebSocketBridge:
    """
    Bridges React frontend WebSocket to OpenAI Realtime API.
    Runs alongside the RealtimeSession.
    """
    
    def __init__(
        self,
        on_transcript: Optional[Callable[[str, str], None]] = None,
        on_audio: Optional[Callable[[bytes], None]] = None,
        on_commit: Optional[Callable[[], None]] = None,
        on_recording_start: Optional[Callable[[], None]] = None,
        on_mail_confirmation: Optional[Callable[[dict[str, Any]], None]] = None,
        on_recording_cancel: Optional[Callable[[], None]] = None,
        host: str = "localhost",
        port: int = 8000
    ):
        self.host = host
        self.port = port
        self.on_transcript = on_transcript
        self.on_audio = on_audio
        self._on_commit = on_commit
        self._on_recording_start = on_recording_start
        self._on_mail_confirmation = on_mail_confirmation
        self._on_recording_cancel = on_recording_cancel
        self._recording_client = None
        
        self.clients: set = set()
        self.server: Optional[websockets.Server] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        
        self.audio_buffer: list = []
        self.is_recording = False
        self.is_speaking = False
        self._assistant_message_id = None
        self._latest_status = {"type": "status", "state": "connected", "message": "J.A.R.V.I.S. SYSTEM ONLINE"}
        self._latest_voice_debug = None
        self._last_audio_level_at = 0.0
        
    def start(self):
        """Start WebSocket server in background thread."""
        self.thread = threading.Thread(target=self._run_server, daemon=True)
        self.thread.start()
        print(f"🌐 WebSocket bridge starting on ws://{self.host}:{self.port}")
        
    def stop(self):
        """Stop the WebSocket server."""
        def shutdown():
            if self.server:
                self.server.close()
            self.loop.stop()
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(shutdown)
            
    def _run_server(self):
        """Run the asyncio event loop with both WebSocket and HTTP servers."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        async def start_servers():
            self.server = await websockets.serve(
                self._handle_client,
                self.host,
                self.port,
                ping_interval=20,
                ping_timeout=10
            )
            print(f"🚀 WebSocket bridge ready at ws://{self.host}:{self.port}/ws")
            
            app = web.Application()
            
            cors = aiohttp_cors.setup(app, defaults={
                "*": aiohttp_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_headers="*",
                    allow_methods="*"
                )
            })
            
            register_routes(app)
            
            for route in list(app.router.routes()):
                cors.add(route)
            
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, self.host, self.port + 1)
            await site.start()
            print(f"🚀 HTTP API ready at http://{self.host}:{self.port + 1}")
        
        self.loop.run_until_complete(start_servers())
        
        try:
            self.loop.run_forever()
        except asyncio.CancelledError:
            pass

    @staticmethod
    def _decode_message(message: str) -> dict[str, Any]:
        """Parse a client websocket payload safely."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    async def _broadcast_json(self, payload: dict[str, Any]) -> None:
        """Broadcast a JSON payload to all clients."""
        await self.broadcast(payload)

    def _set_recording_state(self, is_recording: bool) -> None:
        self.is_recording = is_recording
        if not is_recording:
            self._recording_client = None
        if is_recording:
            self.audio_buffer = []
            if hasattr(self, '_chunk_count'):
                self._chunk_count = 0

    async def _handle_toggle_recording(self) -> None:
        self._set_recording_state(not self.is_recording)

        await self._broadcast_json({
            "type": "recording",
            "isRecording": self.is_recording,
        })

        if self.is_recording:
            print("🎙️ Started recording from frontend")
            if self._on_recording_start:
                self._on_recording_start()
            return

        print("🛑 Stopped recording")
        await self._process_recorded_audio()

    async def _handle_set_recording(self, enabled: bool) -> None:
        if enabled == self.is_recording:
            # Taking over from native capture still needs to reset the buffer.
            if enabled and self._on_recording_start:
                self._on_recording_start()
            return
        await self._handle_toggle_recording()

    async def _handle_audio_chunk(self, data: dict[str, Any]) -> None:
        if not self.is_recording or not self.on_audio:
            return

        audio_data = data.get("data")
        if not isinstance(audio_data, str) or not audio_data:
            return

        try:
            audio_bytes = base64.b64decode(audio_data)
        except Exception:
            print("⚠️  Ignoring malformed audio chunk")
            return

        if not audio_bytes or len(audio_bytes) % 4 or len(audio_bytes) > 65536:
            return
        audio_array = np.frombuffer(audio_bytes, dtype=np.float32)
        if not np.isfinite(audio_array).all():
            return
        pcm16_bytes = self._float_to_pcm16(audio_array)

        if not hasattr(self, '_chunk_count'):
            self._chunk_count = 0
        self._chunk_count += 1
        if self._chunk_count % 50 == 0:
            print(f"📥 Bridge forwarded {self._chunk_count} chunks (recording={self.is_recording})")

        self.on_audio(pcm16_bytes)

    async def _handle_client(self, websocket):
        """Handle a WebSocket client connection."""
        self.clients.add(websocket)
        client_id = id(websocket)
        print(f"🟢 Frontend connected [{client_id}]")
        
        await self._send_to_client(websocket, self._latest_status)
        await self._send_to_client(websocket, {"type": "recording", "isRecording": self.is_recording})
        await self._send_to_client(websocket, {"type": "speaking", "isSpeaking": self.is_speaking})
        if self._latest_voice_debug is not None:
            await self._send_to_client(websocket, self._latest_voice_debug)
        
        await self._send_to_client(websocket, {
            "type": "message",
            "role": "assistant",
            "text": "Say Hey Jarvis once, then keep talking after each reply. No buttons needed."
        })
        
        try:
            async for message in websocket:
                await self._handle_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            if self._recording_client is websocket:
                self._recording_client = None
                self.set_recording_state(False)
                if self._on_recording_cancel:
                    self._on_recording_cancel()
            print(f"🔴 Frontend disconnected [{client_id}]")
            
    async def _handle_message(self, websocket, message: str):
        """Handle messages from frontend."""
        try:
            data = self._decode_message(message)
            if not data:
                print("⚠️  Ignoring malformed websocket message")
                return

            msg_type = data.get("type")

            if msg_type == "toggle_recording":
                self._recording_client = websocket
                await self._handle_toggle_recording()
            elif msg_type == "set_recording" and isinstance(data.get("isRecording"), bool):
                if self._recording_client not in (None, websocket):
                    return
                enabled = data["isRecording"]
                self._recording_client = websocket if enabled else None
                await self._handle_set_recording(enabled)
            elif msg_type == "audio_chunk":
                if self._recording_client is websocket:
                    await self._handle_audio_chunk(data)
            elif msg_type == "confirm_mail_draft":
                await self._handle_mail_confirmation(data)

        except Exception as e:
            print(f"Error handling message: {e}")

    async def _handle_mail_confirmation(self, data: dict[str, Any]) -> None:
        if not self._on_mail_confirmation:
            return

        self._on_mail_confirmation(data)
            
    async def _process_recorded_audio(self):
        """Commit audio buffer and create response."""
        print(f"🔔 _process_recorded_audio called, has _on_commit: {hasattr(self, '_on_commit')}")
        if not self._on_commit:
            print("⚠️  _on_commit callback not set!")
            return
        print("🔔 Calling _on_commit callback...")
        self._on_commit()
            
    def _float_to_pcm16(self, audio_array: np.ndarray) -> bytes:
        """Convert float32 audio to PCM16 bytes."""
        audio_array = np.clip(audio_array, -1.0, 1.0)
        pcm16 = (audio_array * 32767).astype(np.int16)
        return pcm16.tobytes()
        
    async def _send_to_client(self, websocket, data: dict):
        """Send message to a specific client."""
        try:
            await websocket.send(json.dumps(data))
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"Error sending message to client: {e}")
            
    async def broadcast(self, data: dict):
        """Broadcast message to all connected clients."""
        if not self.clients:
            return
            
        message = json.dumps(data)
        disconnected = set()
        
        for client in tuple(self.clients):
            try:
                await asyncio.wait_for(client.send(message), timeout=2.0)
            except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError):
                disconnected.add(client)
                
        for client in disconnected:
            self.clients.discard(client)

    def _broadcast_event(self, data: dict) -> None:
        if not self.loop:
            return

        asyncio.run_coroutine_threadsafe(self.broadcast(data), self.loop)

    def start_assistant_message(self, response_id: str):
        self._assistant_message_id = response_id

    def send_transcript(self, role: str, text: str):
        """Send transcript to all frontend clients."""
        self._broadcast_event({
            "type": "message",
            "role": role,
            "text": text,
            **({"id": self._assistant_message_id} if role == "assistant" and self._assistant_message_id else {}),
        })
        
    def send_status(self, state: str, message: str):
        """Send status update to all frontend clients."""
        self._latest_status = {
            "type": "status",
            "state": state,
            "message": message,
        }
        self._broadcast_event(self._latest_status)

    def send_audio_level(self, level: float) -> None:
        """Publish a bounded native input meter without sending microphone audio."""
        now = time.monotonic()
        if now - self._last_audio_level_at < 0.07:
            return
        self._last_audio_level_at = now
        self._broadcast_event({
            "type": "audio_level",
            "level": min(1.0, max(0.0, float(level))),
        })

    def send_voice_debug(self, data: dict[str, Any]) -> None:
        """Send native voice listener diagnostics to the frontend."""
        payload = {
            "type": "voice_debug",
            "armed": bool(data.get("armed", False)),
            "speaking": bool(data.get("speaking", False)),
            "musicPlaying": bool(data.get("musicPlaying", False)),
            "passiveFollowup": bool(data.get("passiveFollowup", False)),
            "recording": bool(data.get("recording", False)),
            "skipReason": str(data.get("skipReason", "")),
            "cooldownRemaining": float(data.get("cooldownRemaining", 0.0)),
            "micResumeRemaining": float(data.get("micResumeRemaining", 0.0)),
            "listenWindowRemaining": float(data.get("listenWindowRemaining", 0.0)),
            "status": str(data.get("status", "idle")),
        }
        self._latest_voice_debug = payload
        self._broadcast_event(payload)

    def send_mail_draft(self, draft: dict[str, Any]):
        """Send a structured mail draft preview to the frontend."""
        payload = {
            "type": "mail_draft",
            "account": draft.get("account", "gmail"),
            "to": draft.get("to", ""),
            "subject": draft.get("subject", ""),
            "body": draft.get("body", ""),
            "rawText": draft.get("rawText", ""),
            "cleared": bool(draft.get("cleared", False)),
        }
        self._broadcast_event(payload)
        
    def set_recording_state(self, is_recording: bool):
        """Update recording state."""
        self._set_recording_state(is_recording)

        if is_recording:
            print("🎙️ Started recording - audio tracking reset")

        self._broadcast_event({
            "type": "recording",
            "isRecording": is_recording,
        })
        
    def set_speaking_state(self, is_speaking: bool):
        """Update speaking state - mutes mic input when JARVIS is talking."""
        if self.is_speaking == is_speaking:
            return
            
        self.is_speaking = is_speaking
        print(f"🔊 JARVIS speaking: {is_speaking}")

        self._broadcast_event({
            "type": "speaking",
            "isSpeaking": is_speaking,
        })


_bridge_instance: Optional[WebSocketBridge] = None

def get_bridge() -> Optional[WebSocketBridge]:
    """Get the global bridge instance."""
    return _bridge_instance

def create_bridge(**kwargs) -> WebSocketBridge:
    """Create and start a new bridge instance."""
    global _bridge_instance
    _bridge_instance = WebSocketBridge(**kwargs)
    _bridge_instance.start()
    return _bridge_instance

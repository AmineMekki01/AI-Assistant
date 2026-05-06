from __future__ import annotations

import asyncio
import base64
import importlib
import json
import types
from types import SimpleNamespace

import numpy as np
import pytest

from app.core import websocket_bridge as bridge_module


class FakeWebSocket:
    def __init__(self, incoming=None, send_side_effect=None):
        self.incoming = list(incoming or [])
        self.sent = []
        self.send_side_effect = send_side_effect

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.incoming:
            raise StopAsyncIteration
        return self.incoming.pop(0)

    async def send(self, message):
        if self.send_side_effect:
            return self.send_side_effect(message)
        self.sent.append(message)


class ClosedConnection(Exception):
    pass


bridge_module.websockets.exceptions = SimpleNamespace(ConnectionClosed=ClosedConnection)


class FakeFuture:
    def __init__(self, result_value=None):
        self.result_value = result_value
        self.result_calls = []

    def result(self, timeout=None):
        self.result_calls.append(timeout)
        return self.result_value


class FakeSession:
    last_instance = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.tools = []
        self.connect_called = False
        self.configure_called = False
        self.close_called = False
        self.appended_audio = []
        self.commits = 0
        self.interrupts = 0
        FakeSession.last_instance = self

    async def connect(self):
        self.connect_called = True

    async def configure(self):
        self.configure_called = True

    async def close(self):
        self.close_called = True

    async def append_audio(self, audio_bytes):
        self.appended_audio.append(audio_bytes)

    async def commit_audio(self):
        self.commits += 1

    async def interrupt_active_response(self):
        self.interrupts += 1


@pytest.mark.asyncio
async def test_websocket_bridge_recording_audio_and_message_paths(monkeypatch):
    recorded_payloads = []
    process_calls = []
    audio_calls = []
    recording_starts = []

    bridge = bridge_module.WebSocketBridge(
        on_audio=audio_calls.append,
        on_commit=lambda: process_calls.append("committed"),
        on_recording_start=lambda: recording_starts.append(True),
    )

    assert bridge_module.WebSocketBridge._decode_message("{\"type\": \"hello\"}") == {"type": "hello"}
    assert bridge_module.WebSocketBridge._decode_message("not-json") == {}
    assert bridge_module.WebSocketBridge._decode_message("[1, 2, 3]") == {}

    bridge.audio_buffer = [b"old"]
    bridge._chunk_count = 12
    bridge._set_recording_state(True)
    assert bridge.is_recording is True
    assert bridge.audio_buffer == []
    assert bridge._chunk_count == 0

    bridge.is_recording = False

    original_handle_audio_chunk = bridge._handle_audio_chunk
    original_b64decode = bridge_module.base64.b64decode

    async def fake_broadcast_json(payload):
        recorded_payloads.append(payload)

    async def fake_process_recorded_audio():
        process_calls.append("processed")

    async def fake_handle_audio_chunk(data):
        audio_calls.append(data)

    monkeypatch.setattr(bridge, "_broadcast_json", fake_broadcast_json)
    monkeypatch.setattr(bridge, "_process_recorded_audio", fake_process_recorded_audio)

    await bridge._handle_toggle_recording()
    assert bridge.is_recording is True
    assert recorded_payloads[-1] == {"type": "recording", "isRecording": True}
    assert recording_starts == [True]

    bridge.audio_buffer = [b"sample"]
    await bridge._handle_toggle_recording()
    assert bridge.is_recording is False
    assert recorded_payloads[-1] == {"type": "recording", "isRecording": False}
    assert process_calls == ["processed"]

    async def ignore_toggle():
        recorded_payloads.append({"toggle": True})

    monkeypatch.setattr(bridge, "_handle_toggle_recording", ignore_toggle)
    monkeypatch.setattr(bridge, "_handle_audio_chunk", fake_handle_audio_chunk)
    await bridge._handle_message(object(), "not-json")
    await bridge._handle_message(object(), json.dumps({"type": "toggle_recording"}))
    await bridge._handle_message(object(), json.dumps({"type": "audio_chunk", "data": "abc"}))
    assert audio_calls[-1] == {"type": "audio_chunk", "data": "abc"}

    confirmation_calls = []
    bridge._on_mail_confirmation = confirmation_calls.append
    await bridge._handle_message(object(), json.dumps({"type": "confirm_mail_draft", "accepted": True}))
    await bridge._handle_message(object(), json.dumps({"type": "confirm_mail_draft", "accepted": False}))
    assert confirmation_calls == [
        {"type": "confirm_mail_draft", "accepted": True},
        {"type": "confirm_mail_draft", "accepted": False},
    ]

    captured = []
    def fake_run_coroutine_threadsafe(coro, loop):
        captured.append((coro, loop))
        coro.close()
        return FakeFuture()

    monkeypatch.setattr(bridge_module.asyncio, "run_coroutine_threadsafe", fake_run_coroutine_threadsafe)
    bridge.loop = object()
    bridge._broadcast_event({"type": "status", "state": "connected"})
    assert captured[0][1] is bridge.loop

    bridge.loop = None
    bridge._broadcast_event({"type": "status", "state": "idle"})
    assert len(captured) == 1

    bridge.send_transcript("assistant", "hello")
    bridge.send_status("ready", "online")
    bridge.set_recording_state(True)
    bridge.set_speaking_state(True)
    bridge.set_speaking_state(True)
    assert bridge.is_speaking is True

    async def fake_broadcast(payload):
        recorded_payloads.append(payload)

    monkeypatch.setattr(bridge, "_broadcast_event", lambda payload: recorded_payloads.append(payload))
    bridge.send_transcript("assistant", "hello again")
    bridge.send_status("ready", "online again")
    bridge.set_recording_state(False)
    bridge.set_speaking_state(False)

    assert {"type": "message", "role": "assistant", "text": "hello again"} in recorded_payloads
    assert {"type": "status", "state": "ready", "message": "online again"} in recorded_payloads
    assert {"type": "recording", "isRecording": False} in recorded_payloads
    assert {"type": "speaking", "isSpeaking": False} in recorded_payloads

    pcm = bridge._float_to_pcm16(np.array([0.0, 1.0, -1.0], dtype=np.float32))
    assert pcm == np.array([0, 32767, -32767], dtype=np.int16).tobytes()

    monkeypatch.setattr(bridge_module.base64, "b64decode", lambda value: (_ for _ in ()).throw(ValueError("bad payload")))
    bridge.is_recording = True
    bridge.on_audio = audio_calls.append
    await original_handle_audio_chunk({"data": "AAAA"})
    assert audio_calls == [{"type": "audio_chunk", "data": "abc"}]

    raw_audio = np.array([0.0, 1.0], dtype=np.float32).tobytes()
    encoded_audio = base64.b64encode(raw_audio).decode()
    monkeypatch.setattr(bridge_module.base64, "b64decode", original_b64decode)
    audio_calls.clear()
    await original_handle_audio_chunk({"data": encoded_audio})
    assert audio_calls[0] == np.array([0, 32767], dtype=np.int16).tobytes()

    bridge.on_audio = None
    await original_handle_audio_chunk({"data": encoded_audio})
    assert len(audio_calls) == 1


@pytest.mark.asyncio
async def test_websocket_bridge_lifecycle_and_factory(monkeypatch):
    bridge = bridge_module.WebSocketBridge()
    bridge_module.websockets.exceptions.ConnectionClosed = ClosedConnection

    client_ok = FakeWebSocket()
    client_bad = FakeWebSocket(send_side_effect=lambda message: (_ for _ in ()).throw(ClosedConnection("gone")))
    bridge.clients = {client_ok, client_bad}

    await bridge.broadcast({"type": "status", "message": "hi"})
    assert len(client_ok.sent) == 1
    assert client_bad not in bridge.clients

    sent_messages = []
    websocket = FakeWebSocket([
        json.dumps({"type": "toggle_recording"}),
        json.dumps({"type": "audio_chunk", "data": "abc"}),
    ])

    async def fake_handle_message(ws, message):
        sent_messages.append(message)

    monkeypatch.setattr(bridge, "_handle_message", fake_handle_message)
    await bridge._handle_client(websocket)
    assert len(websocket.sent) == 2
    assert json.loads(websocket.sent[0])["type"] == "status"
    assert sent_messages == [json.dumps({"type": "toggle_recording"}), json.dumps({"type": "audio_chunk", "data": "abc"})]
    assert websocket not in bridge.clients

    class DummyBridge(bridge_module.WebSocketBridge):
        started = False

        def start(self):
            self.started = True

    monkeypatch.setattr(bridge_module, "WebSocketBridge", DummyBridge)
    created = bridge_module.create_bridge(host="127.0.0.1", port=9000)
    assert bridge_module.get_bridge() is created
    assert created.started is True


@pytest.mark.asyncio
async def test_websocket_bridge_send_to_client_handles_errors():
    bridge = bridge_module.WebSocketBridge()

    class BrokenWebSocket:
        async def send(self, message):
            raise RuntimeError("send failed")

    await bridge._send_to_client(BrokenWebSocket(), {"type": "status"})


@pytest.mark.asyncio
async def test_main_app_session_wiring_and_shutdown(monkeypatch):
    main = importlib.import_module("main")

    bridge = SimpleNamespace(
        is_speaking=False,
        status_calls=[],
        transcript_calls=[],
        speaking_calls=[],
        stop_called=False,
    )

    def send_status(state, message):
        bridge.status_calls.append((state, message))

    def send_transcript(role, text):
        bridge.transcript_calls.append((role, text))

    def set_speaking_state(flag):
        bridge.speaking_calls.append(flag)
        bridge.is_speaking = flag

    def stop():
        bridge.stop_called = True

    bridge.send_status = send_status
    bridge.send_transcript = send_transcript
    bridge.set_speaking_state = set_speaking_state
    bridge.stop = stop

    scheduled_tasks = []
    monkeypatch.setattr(main, "create_bridge", lambda **kwargs: bridge)
    monkeypatch.setattr(main, "get_bridge", lambda: bridge)

    fake_music_library_module = types.ModuleType("app.tools.music_library")

    async def fake_ensure_loaded():
        return None

    fake_music_library_module.ensure_loaded = fake_ensure_loaded
    monkeypatch.setitem(importlib.import_module("sys").modules, "app.tools.music_library", fake_music_library_module)

    created_sessions = []

    class BootstrapSession(FakeSession):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            created_sessions.append(self)
            self.tools = []

    monkeypatch.setattr(main, "RealtimeSession", BootstrapSession)

    async def fake_sleep(seconds):
        raise RuntimeError("stop loop")

    def fake_create_task(coro):
        scheduled_tasks.append(coro)
        coro.close()
        return SimpleNamespace()

    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main.asyncio, "create_task", fake_create_task)

    app = main.JarvisWebSocketApp()
    app.bridge = bridge
    await app._connect_session()

    assert created_sessions[0].connect_called is True
    assert created_sessions[0].configure_called is True
    assert bridge.status_calls[0] == ("connected", "J.A.R.V.I.S. SYSTEM ONLINE")
    assert bridge.status_calls[-1] == ("error", "stop loop")
    assert len(scheduled_tasks) == 1

    future_calls = []

    def fake_run_coroutine_threadsafe(coro, loop):
        future_calls.append((coro, loop))
        try:
            coro.send(None)
        except StopIteration:
            pass
        return FakeFuture()

    monkeypatch.setattr(main.asyncio, "run_coroutine_threadsafe", fake_run_coroutine_threadsafe)

    app.session = created_sessions[0]
    app.event_loop = object()
    app.bridge = bridge
    app.bridge.is_recording = False
    app._speaking_timer = SimpleNamespace(cancel=lambda: bridge.speaking_calls.append("timer-cancelled"))

    app._on_transcript("assistant", "Hello there")
    app._on_status("ready", "Online")
    app._on_speaking(True)
    assert app._native_mic_resume_at == float("inf")

    app._on_audio(b"abc")
    assert created_sessions[0].appended_audio == []

    bridge.is_speaking = False
    previous_speaking_calls = len(bridge.speaking_calls)
    app._on_audio(b"outgoing-bytes")
    assert len(bridge.speaking_calls) == previous_speaking_calls + 1
    assert bridge.speaking_calls[-1] is True
    assert app._native_mic_resume_at == float("inf")

    app._on_speaking(False)
    bridge.is_speaking = False

    app._on_input_audio(b"abc")
    assert created_sessions[0].appended_audio == [b"abc"]
    assert app.audio_queue.qsize() >= 1

    app._on_commit_audio()
    assert created_sessions[0].commits == 0
    assert app._total_audio_sent == 0
    assert app._audio_chunk_count == 0

    app.audio_queue.put(b"queued-bytes")
    app._on_recording_start()
    assert created_sessions[0].interrupts == 1
    assert app.audio_queue.empty() is True
    assert bridge.speaking_calls[-1] is False
    assert app._speaking_timer is None

    app._on_speaking(False)
    assert app._native_mic_resume_at > 0

    app.stop()
    assert bridge.stop_called is True
    assert created_sessions[0].close_called is True
    assert future_calls


def test_main_music_playing_gate_blocks_microphone(monkeypatch):
    main = importlib.import_module("main")

    calls = []

    def fake_is_music_playing():
        calls.append(True)
        return True

    monkeypatch.setattr(main, "is_music_playing", fake_is_music_playing)

    app = main.JarvisWebSocketApp()
    app._native_voice_armed = True
    app._recording_audio_buffer = [b"old"]
    app._audio_chunk_count = 4
    app._total_audio_sent = 128

    bridge = SimpleNamespace(is_recording=False, set_recording_state=lambda flag: None, is_speaking=False)
    app.bridge = bridge

    assert main.is_music_playing() is True
    if main.is_music_playing():
        app._recording_audio_buffer = []
        app._audio_chunk_count = 0
        app._total_audio_sent = 0
        app.bridge.set_recording_state(False)
        app._native_voice_armed = False

    assert calls
    assert app._native_voice_armed is False
    assert app._recording_audio_buffer == []
    assert app._audio_chunk_count == 0
    assert app._total_audio_sent == 0


def test_native_silence_timeout_adapts_to_longer_speech():
    main = importlib.import_module("main")

    assert main.JarvisWebSocketApp._native_silence_timeout(0.4) == 1.2
    assert main.JarvisWebSocketApp._native_silence_timeout(2.0) == 1.8
    assert main.JarvisWebSocketApp._native_silence_timeout(5.0) == 2.1

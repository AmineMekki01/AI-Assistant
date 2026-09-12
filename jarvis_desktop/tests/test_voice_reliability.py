"""Voice lifecycle regressions. No network, microphones or external actions."""
import asyncio
import io
import json
import sys
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

import main
from app.core import realtime_session as rs
from app.core.websocket_bridge import WebSocketBridge


def app_with_bridge():
    app = main.JarvisWebSocketApp()
    app.bridge = WebSocketBridge()
    return app


def test_pcm_player_cannot_unmute_external_tts(monkeypatch):
    app = app_with_bridge()
    monkeypatch.setattr(main.time, "time", lambda: 100.0)
    app._on_speaking(True)
    app._set_playback_active(True)
    app._set_playback_active(False)
    assert app.bridge.is_speaking  # afplay is still talking
    app._on_speaking(False)
    assert not app.bridge.is_speaking
    assert app._native_mic_resume_at == 100.2
    assert app._native_listening_window_until == 400.0
    app._on_speaking(True)
    app._clear_audio_queue()
    assert app.bridge.is_speaking


def test_voice_does_not_raise_background_noise_threshold():
    app = app_with_bridge()
    for _ in range(100):
        app._update_background_energy(0.001, False)
    before = app._native_background_energy
    for _ in range(1000):
        app._update_background_energy(0.2, True)
    assert app._native_background_energy == before


def test_wake_prefix_preserves_email_and_punctuation():
    app = app_with_bridge()
    assert app._strip_wake_word("Hey Jarvis, email Jane.Doe@example.com: Hi!", "Hey JARVIS") == "email Jane.Doe@example.com: Hi!"
    assert app._strip_wake_word("Jarvison called me", "Hey JARVIS") == "Jarvison called me"


@pytest.mark.asyncio
async def test_pcm_session_config_and_event_iterator_do_not_kill_pump():
    session = rs.RealtimeSession()
    assert session._build_session_config([])['session']['audio']['input']['format']['rate'] == 24000
    session._pump_task = asyncio.create_task(asyncio.Event().wait())
    await session._recv_queue.put({'type': 'one'})
    await session._recv_queue.put({'type': 'two'})
    iterator = session.events()
    assert (await anext(iterator))['type'] == 'one'
    assert (await anext(iterator))['type'] == 'two'
    assert not session._pump_task.done()
    await iterator.aclose()
    await session.close()


@pytest.mark.asyncio
async def test_session_config_rejection_is_reported():
    session = rs.RealtimeSession()
    session.ws = SimpleNamespace(send=AsyncMock())
    await session._recv_queue.put({'type': 'session.created'})
    await session._recv_queue.put({'type': 'error', 'error': {'message': 'invalid format'}})
    with pytest.raises(RuntimeError, match='invalid format'):
        await session.configure()
    assert not session._configured


@pytest.mark.asyncio
async def test_tts_cancellation_kills_process_and_unmutes(monkeypatch):
    started = asyncio.Event()
    class Process:
        returncode = None
        killed = False
        async def wait(self):
            if self.killed: return 0
            started.set()
            await asyncio.Event().wait()
        def kill(self):
            self.killed = True
            self.returncode = -9
    process = Process()
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            return SimpleNamespace(content=b'mp3', raise_for_status=lambda: None)
    monkeypatch.setattr(rs.sys, 'platform', 'darwin')
    monkeypatch.setattr(rs.shutil, 'which', lambda _: '/usr/bin/afplay')
    monkeypatch.setattr(rs.httpx, 'AsyncClient', Client)
    monkeypatch.setattr(rs.asyncio, 'create_subprocess_exec', AsyncMock(return_value=process))
    states = []
    session = rs.RealtimeSession(on_speaking=states.append)
    session.api_key = 'test'
    task = asyncio.create_task(session._speak_with_openai_tts('Hello'))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert process.killed
    assert states == [True, False]
    assert session._tts_process is None


@pytest.mark.asyncio
async def test_bridge_rejects_other_client_and_malformed_audio():
    received = []
    bridge = WebSocketBridge(on_audio=received.append)
    first, second = object(), object()
    await bridge._handle_message(first, json.dumps({'type': 'set_recording', 'isRecording': True}))
    await bridge._handle_message(second, json.dumps({'type': 'set_recording', 'isRecording': False}))
    assert bridge.is_recording
    import base64
    payload = json.dumps({'type': 'audio_chunk', 'data': base64.b64encode(np.ones(32, dtype=np.float32).tobytes()).decode()})
    await bridge._handle_message(second, payload)
    assert not received
    await bridge._handle_message(first, payload)
    assert len(received) == 1
    for raw in [b'x', np.array([np.nan], dtype=np.float32).tobytes()]:
        await bridge._handle_audio_chunk({'data': base64.b64encode(raw).decode()})
    assert len(received) == 1


def test_native_listener_captures_second_turn_without_second_wake_word(monkeypatch):
    """Drive real detection code through wake -> reply -> ordinary follow-up."""
    app = app_with_bridge()
    clock = [100.0]
    played_until = [0.0]
    recordings = []
    predictions = []
    monkeypatch.setattr(main.time, 'time', lambda: clock[0])
    monkeypatch.setattr(main.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(app, '_update_music_listening_volume', lambda *a: None)
    monkeypatch.setattr(app, '_voice_settings', lambda: {'wakeWord': 'Hey Jarvis', 'sensitivity': 0.5})
    monkeypatch.setattr(app, '_detect_clap_trigger', lambda _: False)
    monkeypatch.setattr(main.music_state, 'voice_followup_override_active', lambda: False)

    class Model:
        models = {'hey_jarvis': None}
        prediction_buffer = {'hey_jarvis': [1.0]}
        def __init__(self, **kwargs): pass
        def predict(self, audio): predictions.append(audio)
        def reset(self): pass
    monkeypatch.setitem(sys.modules, 'openwakeword', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'openwakeword.model', SimpleNamespace(Model=Model))
    class VAD:
        def predict(self, audio, frame_size):
            return 0.8 if float(np.mean(audio)) > 50 else 0.01
    monkeypatch.setitem(sys.modules, 'openwakeword.vad', SimpleNamespace(VAD=VAD))
    monkeypatch.setitem(sys.modules, 'openwakeword.utils', SimpleNamespace(download_models=lambda: None))

    # The second request starts 240 ms after playback ends. No wake word.
    samples = iter([1200] * 12 + [10] * 30 + [5000] * 12 + [10] * 3 + [65] * 12 + [10] * 35)
    class CapturedQueue:
        def __init__(self, **kwargs): pass
        def get(self, **kwargs):
            try: energy = next(samples)
            except StopIteration:
                app._native_voice_stop.set()
                raise main.queue.Empty
            clock[0] += 0.08
            if app._speech_active and clock[0] >= played_until[0]:
                app._on_speaking(False)
            return clock[0], np.full(1280, energy, dtype=np.int16).tobytes()
    monkeypatch.setattr(main.queue, 'Queue', CapturedQueue)
    class Audio:
        def open(self, **kwargs):
            assert callable(kwargs['stream_callback'])
            return SimpleNamespace(is_active=lambda: True, stop_stream=lambda: None, close=lambda: None)
        def terminate(self): pass
    monkeypatch.setitem(sys.modules, 'pyaudio', SimpleNamespace(PyAudio=Audio, paInt16=8, paContinue=0))
    def commit():
        recordings.append(list(app._recording_audio_buffer))
        app._recording_audio_buffer = []
        if len(recordings) == 1:
            app._on_speaking(True)
            played_until[0] = 100 + 54 * 0.08
    monkeypatch.setattr(app, '_on_commit_audio', commit)
    app._native_voice_loop()
    assert len(recordings) == 2
    assert len(predictions) == 1
    second = np.frombuffer(b''.join(recordings[1]), dtype=np.int16)
    assert 65 in second  # far below the old volume-only speech threshold
    assert 5000 not in second
    assert app._native_background_energy < 0.001


def test_soft_continuous_words_keep_recording_open():
    app = app_with_bridge()
    for probability in [0.8, 0.4, 0.3, 0.6, 0.28] * 100:
        speech, _ = app._native_speech_flags(0.0005, probability)
        assert speech
    assert app._native_speech_flags(0.0005, 0.1) == (False, False)
    assert app._native_speech_flags(0.0005, 0.6) == (True, True)

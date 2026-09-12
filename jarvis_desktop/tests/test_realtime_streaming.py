import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from app.core import realtime_session as rs
from app.core.voice_input import RealtimeInputStream, pcm16_to_realtime


class Session:
    def __init__(self):
        self.events = []
        self.block_reply = None
        self.committed = asyncio.Event()
    async def _ensure_connected(self): return True
    async def wait_for_turn(self, timeout=120):
        if self.block_reply is not None: await self.block_reply.wait()
    async def begin_audio_turn(self): self.events.append('begin')
    async def append_audio(self, audio): self.events.append(('audio', audio))
    async def commit_audio(self):
        self.events.append('commit')
        self.committed.set()
    async def discard_audio(self): self.events.append('clear')


@pytest.mark.asyncio
async def test_audio_is_sent_before_recording_ends_and_next_turn_is_ordered():
    session = Session()
    stream = RealtimeInputStream(lambda: session, lambda: None, lambda *a: None)
    audio = np.full(4000, 200, dtype='<i2').tobytes()
    stream.offer('start', 1)
    stream.offer('audio', 1, audio)
    await asyncio.wait_for(stream._queue.join(), 1)
    assert session.events[0] == 'begin'
    assert session.events[1][0] == 'audio'
    assert len(session.events[1][1]) == 12000
    assert 'commit' not in session.events
    stream.offer('end', 1)
    await session.committed.wait()
    stream.offer('start', 2)
    stream.offer('audio', 2, audio)
    stream.offer('end', 2)
    await asyncio.wait_for(stream._queue.join(), 1)
    assert [event for event in session.events if isinstance(event, str)] == ['begin', 'commit', 'begin', 'commit']
    await stream.close()


@pytest.mark.asyncio
async def test_failed_audio_turn_is_not_committed_and_next_turn_recovers():
    session = Session()
    calls = 0
    async def append(audio):
        nonlocal calls
        calls += 1
        if calls == 1: raise ConnectionError('lost connection')
    session.append_audio = append
    errors = []
    stream = RealtimeInputStream(lambda: session, lambda: None, lambda *a: errors.append(a))
    for turn in (1, 2):
        stream.offer('start', turn)
        stream.offer('audio', turn, b'\0\0' * 4000)
        stream.offer('end', turn)
    await asyncio.wait_for(stream._queue.join(), 1)
    assert session.events.count('commit') == 1
    assert len(errors) == 1
    await stream.close()


def test_resampling_preserves_duration_and_amplitude():
    original = np.full(1280, 1600, dtype='<i2')
    output = np.frombuffer(pcm16_to_realtime(original.tobytes()), dtype='<i2')
    assert len(output) == 1920
    assert np.all(output == 1600)


@pytest.mark.asyncio
async def test_provider_audio_and_captions_stream_without_auto_cancel():
    audio, captions = [], []
    session = rs.RealtimeSession(on_audio=audio.append, on_transcript=lambda *parts: captions.append(parts))
    session.send_event = AsyncMock()
    await session._handle_pump_event({'type': 'response.created', 'response': {'id': 'r1'}})
    await session._handle_pump_event({'type': 'response.output_audio.delta', 'delta': base64.b64encode(b'pcm').decode()})
    await session._handle_pump_event({'type': 'response.output_audio_transcript.delta', 'delta': 'Hello'})
    assert audio == [b'pcm']
    assert captions == [('assistant', 'Hello')]
    assert not session.send_event.called
    assert not session._turn_done.is_set()
    await session._handle_pump_event({'type': 'response.done', 'response': {'id': 'r1', 'status': 'completed', 'output': []}})
    assert session._turn_done.is_set()


@pytest.mark.asyncio
async def test_duplicate_transcription_events_do_not_duplicate_history():
    captions = []
    session = rs.RealtimeSession(on_transcript=lambda *parts: captions.append(parts))
    event = {'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'u1', 'transcript': 'Hello'}
    await session._handle_pump_event(event)
    await session._handle_pump_event(event)
    assert captions == [('user', 'Hello')]
    assert list(session._recent_history) == [('user', 'Hello')]


@pytest.mark.asyncio
async def test_late_transcription_preserves_context_order():
    session = rs.RealtimeSession()
    await session._handle_pump_event({'type': 'input_audio_buffer.committed', 'item_id': 'u1'})
    await session._handle_pump_event({'type': 'response.output_audio_transcript.delta', 'delta': 'Hello back'})
    await session._handle_pump_event({'type': 'response.output_audio_transcript.done'})
    await session._handle_pump_event({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'u1', 'transcript': 'Hello'})
    assert list(session._recent_history) == [('user', 'Hello'), ('assistant', 'Hello back')]


@pytest.mark.asyncio
async def test_turn_timeout_stops_tool_continuations():
    session = rs.RealtimeSession()
    session._turn_done.clear()
    session.interrupt_active_response = AsyncMock()
    task = asyncio.create_task(asyncio.sleep(60))
    session._tool_tasks.add(task)
    with pytest.raises(asyncio.TimeoutError):
        await session.wait_for_turn(timeout=0.01)
    assert task.cancelled()
    assert session._turn_done.is_set()


@pytest.mark.asyncio
async def test_voice_mail_confirmation_clears_draft_before_dispatch(monkeypatch):
    events = []
    session = rs.RealtimeSession(on_mail_draft=lambda draft: events.append(('draft', draft)))
    session.send_event = AsyncMock()
    async def execute(*args):
        events.append(('dispatch', None))
        return {'ok': True, 'result': 'Sent'}
    monkeypatch.setattr(rs.REGISTRY, 'call', execute)
    await session._handle_tool_call({'call_id': 'c1', 'name': 'mail_send', 'arguments': '{"confirmed":true}'})
    assert events == [('draft', {'cleared': True}), ('dispatch', None)]


@pytest.mark.asyncio
async def test_tool_batch_executes_once_and_continues_once(monkeypatch):
    session = rs.RealtimeSession()
    session.send_event = AsyncMock()
    call = AsyncMock(return_value={'ok': True, 'result': 'done'})
    monkeypatch.setattr(rs.REGISTRY, 'call', call)
    calls = [{'call_id': f'c{i}', 'name': 'get_time', 'arguments': '{}'} for i in range(2)]
    await session._handle_tool_batch(calls, session._connection_generation)
    assert call.await_count == 2
    payloads = [item.args[0] for item in session.send_event.await_args_list]
    assert [item['type'] for item in payloads] == ['conversation.item.create', 'conversation.item.create', 'response.create']
    await session._handle_tool_batch(calls, session._connection_generation)
    assert call.await_count == 2
    assert session.send_event.await_count == 3


@pytest.mark.asyncio
async def test_invalid_tool_arguments_cannot_execute_action(monkeypatch):
    session = rs.RealtimeSession()
    session.send_event = AsyncMock()
    call = AsyncMock()
    monkeypatch.setattr(rs.REGISTRY, 'call', call)
    await session._handle_tool_call({'call_id': 'bad', 'name': 'computer_open_app', 'arguments': '['})
    call.assert_not_called()
    assert 'no action was executed' in session.send_event.await_args_list[0].args[0]['item']['output']


@pytest.mark.asyncio
async def test_reconnect_does_not_replay_tool_results(monkeypatch):
    session = rs.RealtimeSession()
    session.send_event = AsyncMock()
    async def execute(*args):
        session._connection_generation += 1
        return {'ok': True, 'result': 'done'}
    monkeypatch.setattr(rs.REGISTRY, 'call', execute)
    await session._handle_tool_batch([{'call_id': 'c1', 'name': 'get_time', 'arguments': '{}'}], session._connection_generation)
    session.send_event.assert_not_called()


@pytest.mark.asyncio
async def test_speak_uses_realtime_not_downloaded_mp3(monkeypatch):
    session = rs.RealtimeSession()
    session._ensure_connected = AsyncMock(return_value=True)
    session.send_event = AsyncMock()
    session._speak_with_openai_tts = AsyncMock(side_effect=AssertionError('No MP3 path'))
    await session.speak('Hello', await_completion=False)
    payload = session.send_event.await_args.args[0]
    assert payload['type'] == 'response.create'
    assert payload['response']['tool_choice'] == 'none'
    session._speak_with_openai_tts.assert_not_called()

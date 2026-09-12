"""Ordered, bounded microphone streaming independent of capture and playback."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import numpy as np


def pcm16_to_realtime(audio: bytes) -> bytes:
    """Upsample mono 16 kHz capture to the Realtime API's 24 kHz PCM format."""
    samples = np.frombuffer(audio, dtype='<i2')
    if not samples.size:
        return b''
    positions = np.arange(samples.size * 3 // 2, dtype=np.float64) * (2 / 3)
    return np.interp(positions, np.arange(samples.size), samples).astype('<i2').tobytes()


class RealtimeInputStream:
    def __init__(self, session: Callable, verifier: Callable, status: Callable):
        self._session = session
        self._verifier = verifier
        self._status = status
        self._queue = asyncio.Queue(maxsize=2048)
        self._failed_turns: set[int] = set()
        self._task = None

    def offer(self, kind: str, turn: int, audio: bytes = b'') -> None:
        """Called on the session loop, via call_soon_threadsafe from capture."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name='voice-input')
        try:
            self._queue.put_nowait((kind, turn, audio, time.monotonic()))
        except asyncio.QueueFull:
            self._failed_turns.add(turn)
            self._status('connected', 'Audio connection is behind — please repeat your request')

    async def _run(self):
        current = None
        session = None
        chunks = []
        failed = False
        while True:
            kind, turn, audio, captured = await self._queue.get()
            try:
                if kind == 'start':
                    current, chunks = turn, []
                    failed = turn in self._failed_turns or time.monotonic() - captured > 30
                    if failed:
                        self._status('connected', 'That recording expired — please repeat your request')
                        continue
                    session = self._session()
                    if session is None or not await session._ensure_connected():
                        raise ConnectionError('Realtime voice connection unavailable')
                    await session.wait_for_turn(timeout=120)
                    await session.begin_audio_turn()
                elif turn == current and not failed and turn not in self._failed_turns:
                    if kind == 'audio':
                        chunks.append(audio)
                        await session.append_audio(pcm16_to_realtime(audio))
                    elif kind == 'end':
                        raw = b''.join(chunks)
                        if len(raw) < 6400:
                            await session.discard_audio()
                            continue
                        verifier = self._verifier()
                        if verifier is not None:
                            verification = await asyncio.wait_for(
                                asyncio.to_thread(verifier.verify_audio, raw), timeout=10
                            )
                            if not verification.active or not verification.allowed:
                                await session.discard_audio()
                                reason = getattr(verification, 'reason', '')
                                message = ('Enroll your voice in Settings → Voice to enable voice commands'
                                           if reason == 'no_speaker_profile' else 'Speaker verification rejected — try again')
                                self._status('connected', message)
                                continue
                        await session.commit_audio()
                        # Tool calls and their follow-up speech are part of the
                        # same turn. The microphone continues capturing meanwhile.
                        await session.wait_for_turn(timeout=120)
                    elif kind == 'cancel':
                        await session.discard_audio()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                failed = True
                self._status('connected', f'Voice request interrupted — please try again ({type(error).__name__})')
                if session is not None:
                    try:
                        await session.discard_audio()
                    except Exception:
                        pass
            finally:
                if kind in ('end', 'cancel'):
                    self._failed_turns.discard(turn)
                    if current == turn:
                        current, chunks = None, []
                self._queue.task_done()

    async def close(self):
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

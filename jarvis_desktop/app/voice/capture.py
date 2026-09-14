"""Native microphone capture and wake/speech detection loop."""
from __future__ import annotations

import queue
import time
from typing import TYPE_CHECKING

from app.core import music_state

if TYPE_CHECKING:
    from app.application.assistant import AssistantApplication


def is_music_playing(force_refresh: bool = False) -> bool:
    return music_state.is_music_playing(force_refresh=force_refresh)


class MicrophoneCapture:
    """Native microphone capture and wake/speech detection loop."""

    def __init__(self, app: AssistantApplication):
        self.app = app

    def run(self) -> None:
        try:
            import numpy as np
            import pyaudio
            from openwakeword.model import Model
        except Exception as e:
            print(f"⚠️  [VOICE] Native wake-word listener unavailable: {e}", flush=True)
            self.app.voice._set_voice_status("error", "Native wake word unavailable")
            return

        voice_settings = self.app.voice._voice_settings()
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
            self.app.voice._set_voice_status("error", "Wake word model unavailable")
            return

        p = None
        stream = None
        chunk_size = 1280
        min_recording_duration = 0.65
        listen_window_seconds = self.app.settings.voice_followup_seconds  # 5 minutes follow-up window
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
            self.app.voice._set_voice_status("error", "Microphone unavailable")
            if p is not None:
                p.terminate()
            return

        self.app.voice._set_voice_status("connected", f'Wake word armed — say "{wake_word}"')
        self.app.voice._native_voice_started_at = time.time()
        last_capture_at = time.monotonic()

        try:
            while not self.app.voice._native_voice_stop.is_set():
                try:
                    captured_at, raw_audio = captured_audio.get(timeout=0.25)
                except queue.Empty:
                    if not stream.is_active() or time.monotonic() - last_capture_at > 2.0:
                        raise RuntimeError("Microphone stream stopped")
                    continue
                last_capture_at = time.monotonic()
                if time.monotonic() - captured_at > 0.3:
                    continue
                # The hands-free microphone belongs to the backend. Publish its
                # signal level so the frontend does not need a second mic stream.
                captured_samples = np.frombuffer(raw_audio, dtype=np.int16)
                if self.app.bridge and captured_samples.size:
                    input_level = float(np.mean(np.abs(captured_samples.astype(np.float32))) / 32768.0)
                    self.app.bridge.send_audio_level(input_level * 12.0)
                music_playing = self.app.voice._native_music_playing
                shared_music_override_active = music_state.voice_followup_override_active()
                in_listening_window = time.time() < self.app.voice._native_listening_window_until
                allow_passive_followup = in_listening_window or shared_music_override_active

                if self.app.voice._frontend_recording:
                    self.app.voice._native_pre_roll_audio.clear()
                    self.app.voice._native_speech_streak = 0
                    continue

                if self.app.activation._activation_sequence_running:
                    self.app.voice._send_voice_debug(
                        status="activation_sequence",
                        armed=self.app.voice._native_voice_armed,
                        music_playing=music_playing,
                        allow_passive_followup=False,
                        skip_reason="Activation sequence running",
                    )
                    self.app.voice._native_pre_roll_audio.clear()
                    self.app.voice._native_speech_streak = 0
                    continue

                if self.app.bridge and self.app.bridge.is_speaking:
                    self.app.voice._trace_native_voice_skip("JARVIS is speaking")
                    self.app.voice._send_voice_debug(
                        status="muted_by_speaking",
                        armed=self.app.voice._native_voice_armed,
                        music_playing=music_playing,
                        allow_passive_followup=False,
                        skip_reason="JARVIS is speaking",
                    )
                    if self.app.voice._native_voice_armed:
                        print("🔇 [VOICE] JARVIS speaking — aborting recording", flush=True)
                        self.app.voice._reset_native_recording_state()
                    self.app.voice._native_pre_roll_audio.clear()
                    self.app.voice._native_speech_streak = 0
                    continue

                if time.time() < self.app.voice._native_mic_resume_at:
                    remaining = self.app.voice._native_mic_resume_at - time.time()
                    self.app.voice._trace_native_voice_skip(f"Mic resume delay active ({remaining:.2f}s left)")
                    self.app.voice._send_voice_debug(
                        status="mic_resume_delay",
                        armed=self.app.voice._native_voice_armed,
                        music_playing=music_playing,
                        allow_passive_followup=False,
                        skip_reason="Mic resume delay",
                    )
                    self.app.voice._native_pre_roll_audio.clear()
                    self.app.voice._native_speech_streak = 0
                    continue

                self.app.voice._native_voice_frame_count += 1

                try:
                    audio = np.frombuffer(raw_audio, dtype=np.int16)
                    if audio.size == 0:
                        continue

                    self.app.voice._trace_native_voice_heartbeat(
                        armed=self.app.voice._native_voice_armed,
                        music_playing=music_playing,
                        allow_passive_followup=allow_passive_followup,
                    )

                    if time.time() < self.app.voice._native_voice_cooldown_until and not allow_passive_followup:
                        remaining = self.app.voice._native_voice_cooldown_until - time.time()
                        self.app.voice._trace_native_voice_skip(f"Commit cooldown active ({remaining:.2f}s left)")
                        self.app.voice._send_voice_debug(
                            status="cooldown",
                            armed=self.app.voice._native_voice_armed,
                            music_playing=music_playing,
                            allow_passive_followup=allow_passive_followup,
                            skip_reason="Commit cooldown",
                        )
                        continue

                    if not self.app.voice._native_voice_armed:
                        if allow_passive_followup:
                            self.app.voice._trace_native_voice_skip("Passive follow-up listening")
                            self.app.voice._send_voice_debug(
                                status="passive_followup",
                                armed=False,
                                music_playing=music_playing,
                                allow_passive_followup=True,
                                skip_reason="Passive follow-up listening",
                            )
                        else:
                            self.app.voice._trace_native_voice_skip("Waiting for wake word")
                            self.app.voice._send_voice_debug(
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
                    is_speech_frame, is_start_speech_frame = self.app.voice._native_speech_flags(frame_energy, speech_probability)

                    if not self.app.voice._native_voice_armed and not allow_passive_followup:
                        self.app.voice._native_pre_roll_audio.append(raw_audio)
                        self.app.voice._update_background_energy(frame_energy, is_speech_frame)
                        if not self.app.voice._music_blocks_clap_trigger(music_playing) and self.app.voice._detect_clap_trigger(frame_energy):
                            print("👏 [VOICE] Clap detected — activating assistant", flush=True)
                            self.app.voice._send_voice_debug(
                                status="clap_detected",
                                armed=False,
                                music_playing=music_playing,
                                allow_passive_followup=False,
                                skip_reason="Clap trigger detected",
                            )
                            self.app.activation._trigger_activation_sequence("clap")
                            self.app.voice._native_last_frame_energy = frame_energy
                            continue

                        try:
                            wake_model.predict(audio)
                        except Exception as e:
                            print(f"⚠️  [VOICE] Wake prediction failed: {e}", flush=True)
                            self.app.voice._native_last_frame_energy = frame_energy
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
                            self.app.voice._send_voice_debug(
                                status="wake_word_detected",
                                armed=False,
                                music_playing=music_playing,
                                allow_passive_followup=False,
                                skip_reason="Wake word trigger detected",
                            )
                            # Preserve "Hey Jarvis, <command>" in one breath.
                            # A greeting here used to mute and discard the command.
                            self.app.voice._native_voice_armed = True
                            self.app.voice._native_recording_has_speech = True
                            self.app.voice._native_recording_started_at = time.time()
                            self.app.voice._native_voice_last_activity = time.time()
                            self.app.voice._native_listening_window_until = time.time() + listen_window_seconds
                            self.app.voice._recording_audio_buffer = list(self.app.voice._native_pre_roll_audio)
                            self.app.voice._audio_chunk_count = len(self.app.voice._recording_audio_buffer)
                            self.app.voice._total_audio_sent = sum(map(len, self.app.voice._recording_audio_buffer))
                            self.app.voice._native_pre_roll_audio.clear()
                            self.app.voice._start_input_stream(self.app.voice._recording_audio_buffer)
                            wake_model.reset()
                            if self.app.bridge:
                                self.app.bridge.set_recording_state(True)
                            self.app.voice._set_voice_status("connected", "Wake word detected — listening for your request")
                            self.app.voice._native_last_frame_energy = frame_energy
                            continue

                        self.app.voice._native_last_frame_energy = frame_energy
                        continue

                    if not self.app.voice._native_voice_armed and allow_passive_followup:
                        self.app.voice._native_pre_roll_audio.append(raw_audio)

                        if is_start_speech_frame:
                            self.app.voice._native_voice_last_activity = time.time()
                            self.app.voice._native_speech_streak += 1
                        elif is_speech_frame:
                            self.app.voice._update_background_energy(frame_energy, is_speech_frame)
                            self.app.voice._native_speech_streak = max(0, self.app.voice._native_speech_streak - 1)
                        else:
                            self.app.voice._update_background_energy(frame_energy, is_speech_frame)
                            self.app.voice._native_speech_streak = 0

                        if self.app.voice._native_speech_streak >= speech_frames_required:
                            self.app.voice._native_voice_armed = True
                            self.app.voice._native_voice_last_activity = time.time()
                            self.app.voice._native_recording_started_at = time.time()
                            self.app.voice._native_recording_has_speech = True
                            self.app.voice._recording_audio_buffer = list(self.app.voice._native_pre_roll_audio)
                            self.app.voice._audio_chunk_count = len(self.app.voice._recording_audio_buffer)
                            self.app.voice._total_audio_sent = sum(len(chunk) for chunk in self.app.voice._recording_audio_buffer)
                            self.app.voice._native_pre_roll_audio.clear()
                            self.app.voice._start_input_stream(self.app.voice._recording_audio_buffer)
                            print("🟡 [VOICE] Speech detected — starting native recording", flush=True)
                            self.app.voice._set_voice_status("connected", "Listening — speak your command")
                            if self.app.bridge:
                                self.app.bridge.set_recording_state(True)

                        continue

                    if is_speech_frame:
                        self.app.voice._native_voice_last_activity = time.time()
                        self.app.voice._native_recording_has_speech = True
                    else:
                        self.app.voice._update_background_energy(frame_energy, is_speech_frame)

                    if self.app.bridge and self.app.bridge.is_recording:
                        self.app.voice.receive_audio(raw_audio)

                    recording_duration = time.time() - self.app.voice._native_recording_started_at
                    silence_timeout = self.app.voice._native_silence_timeout(recording_duration)
                    silence_duration = time.time() - self.app.voice._native_voice_last_activity

                    if recording_duration >= self.app.settings.voice_max_recording_seconds or (recording_duration >= min_recording_duration and silence_duration >= silence_timeout):
                        if not self.app.voice._native_recording_has_speech:
                            print("🛑 [VOICE] Silence detected without confirmed speech — discarding native buffer", flush=True)
                            if self.app.bridge:
                                self.app.bridge.set_recording_state(False)
                            self.app.voice._native_voice_armed = False
                            self.app.voice._native_voice_cooldown_until = time.time() + 0.5
                            self.app.voice._native_listening_window_until = time.time() + listen_window_seconds
                            self.app.voice._native_pre_roll_audio.clear()
                            self.app.voice._native_speech_streak = 0
                            self.app.voice._recording_audio_buffer = []
                            continue

                        print(f"🛑 [VOICE] Silence detected (energy={frame_energy:.4f}, silence={silence_duration:.1f}s) — committing native recording", flush=True)
                        if self.app.bridge:
                            self.app.bridge.set_recording_state(False)
                        if self.app.voice._recording_audio_buffer:
                            self.app.voice.commit_recording()
                        self.app.voice._native_voice_armed = False
                        self.app.voice._native_voice_cooldown_until = time.time() + 0.5
                        self.app.voice._native_listening_window_until = time.time() + listen_window_seconds
                        self.app.voice._native_pre_roll_audio.clear()
                        self.app.voice._native_speech_streak = 0
                        print("🟡 [VOICE] Listening window extended — next 5 min no wake word needed", flush=True)
                        self.app.voice._set_voice_status("connected", "Listening window active — speak your command")

                    self.app.voice._native_last_frame_energy = frame_energy

                except Exception as e:
                    print(f"⚠️  [VOICE] Native iteration error: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
                    time.sleep(0.2)
                    continue

        except Exception as e:
            print(f"💥 [VOICE] Native wake loop crashed: {e}", flush=True)
            self.app.voice._set_voice_status("error", "Wake word listener crashed")
        finally:
            self.app.audio._update_music_listening_volume(False, False)
            self.app.voice._native_voice_armed = False
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
            self.app.voice._set_voice_status("connected", "Voice wake stopped")

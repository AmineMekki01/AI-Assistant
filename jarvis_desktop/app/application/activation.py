"""Activation greeting, startup briefing, and activation sound coordination."""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from app.core import music_state

if TYPE_CHECKING:
    from app.application.assistant import AssistantApplication


def is_music_playing(force_refresh: bool = False) -> bool:
    return music_state.is_music_playing(force_refresh=force_refresh)


class ActivationController:
    """Activation greeting, startup briefing, and activation sound coordination."""

    def __init__(self, app: AssistantApplication):
        self.app = app
        self._activation_sequence_running = False

    def _activation_voice_settings(self) -> dict:
        voice = self.app.voice._voice_settings()
        return {
            "enabled": bool(voice.get("enabled", True)),
            "wakeWord": str(voice.get("wakeWord") or "Hey JARVIS").strip() or "Hey JARVIS",
            "sensitivity": float(voice.get("sensitivity", 0.5)),
            "clapEnabled": bool(voice.get("clapEnabled", True)),
            "introSoundPath": str(voice.get("introSoundPath") or "").strip(),
            "activationGreeting": str(voice.get("activationGreeting") or "Welcome home, sir.").strip() or "Welcome home, sir.",
            "announceStatus": bool(voice.get("announceStatus", True)),
            "announceCalendar": bool(voice.get("announceCalendar", True)),
        }

    @staticmethod
    def _summarize_calendar_output(raw_output: str) -> str:
        lines = [line.strip() for line in (raw_output or "").splitlines() if line.strip()]
        if not lines:
            return ""

        if lines[0].lower().startswith("error"):
            return ""

        if lines[0].lower().startswith("no events"):
            return "No upcoming calendar events."

        items: list[str] = []
        for line in lines:
            if line.startswith("──"):
                continue
            if "event(s)" in line and line.endswith(":"):
                continue

            cleaned = line.lstrip("•").strip()
            if "|" in cleaned:
                when_part, summary_part = cleaned.split("|", 1)
                when = when_part.replace("->", "to").strip()
                summary = summary_part.strip()
                if summary:
                    items.append(f"{summary} at {when}")
            elif cleaned:
                items.append(cleaned)

            if len(items) >= 2:
                break

        if not items:
            return ""
        if len(items) == 1:
            return f"Your next calendar item is {items[0]}."
        return "Your next calendar items are " + "; ".join(items) + "."

    async def _wait_for_session_ready(self, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.app.session is not None:
                return True
            await asyncio.sleep(0.1)
        return self.app.session is not None

    async def _play_activation_sound(self, sound_path: str) -> bool:
        if not sound_path:
            return False

        path = Path(sound_path).expanduser()
        if not path.exists():
            print(f"ℹ️  [VOICE] Activation sound not found: {path}", flush=True)
            return False

        import shutil

        if not shutil.which("afplay"):
            print("ℹ️  [VOICE] Cannot play activation sound: afplay unavailable", flush=True)
            return False

        process = None
        try:
            volume = os.getenv("JARVIS_ACTIVATION_SOUND_VOLUME", "0.65")
            process = await asyncio.create_subprocess_exec(
                "afplay",
                "-v",
                volume,
                str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), timeout=10.0)
            return process.returncode == 0
        except Exception as e:
            print(f"⚠️  [VOICE] Activation sound playback failed: {e}", flush=True)
            return False
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()

    async def _speak_activation_text(self, text: str) -> None:
        if not text:
            return

        if self.app.session is None and not await self._wait_for_session_ready(timeout=5.0):
            print("ℹ️  [VOICE] Activation speech skipped: realtime session not ready", flush=True)
            return

        if self.app.session is not None:
            await self.app.session.speak(text)

    async def _build_activation_summary(self) -> str:
        try:
            startup_task = (
                "Produce a very short startup briefing for the user. Keep it to 2-4 "
                "short spoken sentences. Cover the current day, the next 24 hours, "
                "urgent calendar items, unread or actionable mail, and any important "
                "notes or reminders that change the startup picture. Do not use "
                "headings or a preface."
            )
            context_parts: list[str] = ["This is the JARVIS startup sequence."]

            try:
                settings = self.app.settings
                speaker_verification_enabled = bool(settings.speaker_verification_enabled)
            except Exception:
                speaker_verification_enabled = self.app.voice._speaker_verifier is not None

            if self.app.session and getattr(self.app.session, "_ws_alive", None) and self.app.session._ws_alive():
                context_parts.append("The realtime connection is online.")
            elif self.app.session:
                context_parts.append("The realtime connection is still coming online.")
            else:
                context_parts.append("The realtime session is still starting.")

            if speaker_verification_enabled:
                verifier = self.app.voice._get_speaker_verifier()
                profile_path = getattr(verifier, "profile_path", None) if verifier is not None else None
                if verifier is not None and profile_path is not None and getattr(profile_path, "exists", lambda: False)():
                    context_parts.append("Speaker verification is ready.")
                else:
                    context_parts.append("Speaker verification is enabled, but no profile is enrolled yet.")
            else:
                context_parts.append("Speaker verification is not enabled.")

            voice = self._activation_voice_settings()
            if voice["clapEnabled"]:
                context_parts.append("Clap and wake word are armed.")
            else:
                context_parts.append("Wake word is armed.")

            if voice["announceCalendar"]:
                context_parts.append("Calendar details are allowed in the startup summary.")

            result = await self.app.registry.call(
                "delegate_to_startup_briefing",
                {
                    "task": startup_task,
                    "context": " ".join(context_parts),
                },
            )
            if result.get("ok"):
                summary = str(result.get("result") or "").strip()
                if summary:
                    return summary
                print("ℹ️  [VOICE] Startup briefing agent returned no text; using fallback summary", flush=True)
            else:
                print(
                    f"ℹ️  [VOICE] Startup briefing agent failed: {result.get('error', 'unknown error')}; using fallback summary",
                    flush=True,
                )
        except Exception as e:
            print(f"⚠️  [VOICE] Startup briefing agent lookup failed: {e}; using fallback summary", flush=True)

        return self._build_activation_summary_fallback()

    async def _build_activation_summary_fallback(self) -> str:
        voice = self._activation_voice_settings()
        try:
            settings = self.app.settings
            speaker_verification_enabled = bool(settings.speaker_verification_enabled)
        except Exception:
            speaker_verification_enabled = self.app.voice._speaker_verifier is not None

        parts: list[str] = []

        if self.app.session and getattr(self.app.session, "_ws_alive", None) and self.app.session._ws_alive():
            parts.append("Connections are online.")
        elif self.app.session:
            parts.append("The realtime connection is coming online.")
        else:
            parts.append("The realtime session is still starting.")

        if speaker_verification_enabled:
            verifier = self.app.voice._get_speaker_verifier()
            profile_path = getattr(verifier, "profile_path", None) if verifier is not None else None
            if verifier is not None and profile_path is not None and getattr(profile_path, "exists", lambda: False)():
                parts.append("Speaker verification is ready.")
            else:
                parts.append("Speaker verification is enabled, but no profile is enrolled yet.")
        else:
            parts.append("Speaker verification is not enabled.")

        if voice["clapEnabled"]:
            parts.append("Clap and wake word are armed.")
        else:
            parts.append("Wake word is armed.")

        if voice["announceCalendar"]:
            try:
                result = await asyncio.wait_for(self.app.registry.call("calendar_list", {"max_results": 3}), timeout=1.5)
                if result.get("ok"):
                    calendar_summary = self._summarize_calendar_output(str(result.get("result") or ""))
                    if calendar_summary:
                        parts.append(calendar_summary)
            except asyncio.TimeoutError:
                print("ℹ️  [VOICE] Calendar summary timed out; speaking status without events", flush=True)
            except Exception as e:
                print(f"⚠️  [VOICE] Calendar summary failed: {e}", flush=True)

        return " ".join(parts)

    def _trigger_activation_sequence(self, trigger: str) -> None:
        if self._activation_sequence_running:
            return
        if not self.app.event_loop:
            print(f"ℹ️  [VOICE] Activation trigger ignored: event loop not ready ({trigger})", flush=True)
            return

        self._activation_sequence_running = True
        future = asyncio.run_coroutine_threadsafe(
            asyncio.wait_for(self._run_activation_sequence(trigger), timeout=45.0), self.app.event_loop
        )

        def _release(_future):
            self._activation_sequence_running = False
            try:
                _future.result()
            except Exception as e:
                print(f"⚠️ [VOICE] Activation ended early: {e}", flush=True)
                self.app.voice._set_voice_status("connected", "Listening for your request")

        future.add_done_callback(_release)

    async def _run_activation_sequence(self, trigger: str) -> None:
        summary_task = sound_task = None
        try:
            voice = self._activation_voice_settings()
            intro_sound_path = voice["introSoundPath"]
            self.app.voice._native_voice_cooldown_until = time.time() + 3.0
            self.app.voice._native_clap_cooldown_until = time.time() + 2.0
            self.app.voice._native_voice_armed = False
            self.app.voice._native_recording_has_speech = False
            self.app.voice._recording_audio_buffer = []
            self.app.voice._audio_chunk_count = 0
            self.app.voice._total_audio_sent = 0
            self.app.voice._native_speech_streak = 0
            self.app.voice._native_pre_roll_audio.clear()
            self.app.voice._native_listening_window_until = time.time() + self.app.settings.voice_followup_seconds
            if self.app.bridge:
                self.app.bridge.set_recording_state(False)

            summary_task = None
            if voice["announceStatus"]:
                summary_task = asyncio.create_task(self._build_activation_summary())

            sound_task = None
            if intro_sound_path:
                sound_task = asyncio.create_task(self._play_activation_sound(intro_sound_path))

            if summary_task is not None or sound_task is not None:
                await asyncio.sleep(0)

            if self.app.session is None and not await self._wait_for_session_ready(timeout=5.0):
                print(f"ℹ️  [VOICE] Activation sequence skipped speech: session not ready ({trigger})", flush=True)
                if sound_task is not None:
                    await sound_task
                if summary_task is not None:
                    await summary_task
                return

            if voice["activationGreeting"]:
                await self._speak_activation_text(voice["activationGreeting"])

            if sound_task is not None:
                await sound_task

            if voice["announceStatus"]:
                if summary_task is not None:
                    activation_summary = await summary_task
                else:
                    activation_summary = await self._build_activation_summary()
                if activation_summary:
                    await self._speak_activation_text(activation_summary)
        finally:
            pending = [task for task in (summary_task, sound_task) if task is not None and not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self._activation_sequence_running = False

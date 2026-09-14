"""Background reminder delivery and repeat-alert suppression."""
from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING

from app.core import music_state

if TYPE_CHECKING:
    from app.application.assistant import AssistantApplication


def is_music_playing(force_refresh: bool = False) -> bool:
    return music_state.is_music_playing(force_refresh=force_refresh)


class ReminderScheduler:
    """Background reminder delivery and repeat-alert suppression."""

    def __init__(self, app: AssistantApplication):
        self.app = app
        self._reminder_poller_thread: threading.Thread | None = None
        self._reminder_poller_stop = threading.Event()
        self._reminder_last_alerted: dict[str, float] = {}

    def start(self) -> None:
        """Start the background reminder poller thread."""
        if self._reminder_poller_thread and self._reminder_poller_thread.is_alive():
            return
        self._reminder_poller_stop.clear()
        self._reminder_poller_thread = threading.Thread(target=self._reminder_poller_loop, daemon=True)
        self._reminder_poller_thread.start()
        print("⏰ Reminder poller started", flush=True)

    def stop(self) -> None:
        """Signal the reminder poller to stop."""
        self._reminder_poller_stop.set()

    def _reminder_poller_loop(self) -> None:
        """Background loop: check for due reminders every 10 seconds and alert the user."""
        try:
            from app.tools.reminders import _due_notes, _mark_reminded
        except Exception as e:
            print(f"⚠️  Reminder poller unavailable: {e}", flush=True)
            return

        CHECK_INTERVAL = 10.0
        DEDUP_WINDOW = 60.0  # Don't re-alert the same reminder within 60s

        while not self._reminder_poller_stop.is_set():
            try:
                due = _due_notes()
                now = time.time()
                for reminder in due:
                    rid = reminder.get("id", "")
                    text = reminder.get("text", "")
                    if not rid or not text:
                        continue
                    last_alerted = self._reminder_last_alerted.get(rid, 0)
                    if now - last_alerted < DEDUP_WINDOW:
                        continue

                    # Alert: play a soft chime if available, then speak
                    print(f"⏰ Reminder due: {text}", flush=True)
                    self._reminder_last_alerted[rid] = now
                    _mark_reminded(rid)

                    if self.app.bridge:
                        self.app.bridge.send_status("connected", f"Reminder: {text}")

                    # Speak the reminder if session is ready
                    if self.app.session is not None and self.app.event_loop is not None:
                        alert_text = f"Sir, it's time: {text}."
                        try:
                            future = asyncio.run_coroutine_threadsafe(
                                self.app.session.speak(alert_text),
                                self.app.event_loop,
                            )
                            future.result(timeout=5)
                        except Exception as e:
                            print(f"⚠️  Failed to speak reminder: {e}", flush=True)
            except Exception as e:
                print(f"⚠️  Reminder poller error: {e}", flush=True)

            # Sleep in small increments so we can exit promptly
            for _ in range(int(CHECK_INTERVAL * 2)):
                if self._reminder_poller_stop.is_set():
                    break
                time.sleep(0.5)

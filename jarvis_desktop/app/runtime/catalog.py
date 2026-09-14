"""Built-in capability catalogue and extension point."""
from __future__ import annotations

from collections.abc import Iterable


BUILTIN_CAPABILITY_MODULES: tuple[str, ...] = (
    "app.tools.websearch", "app.tools.knowledge", "app.tools.memory",
    "app.tools.music_library", "app.tools.music_playback", "app.tools.system_control",
    "app.tools.datetime_tool", "app.tools.quick_notes", "app.tools.reminders",
    "app.tools.mail_templates",
    "app.actions.mail", "app.actions.calendar", "app.actions.music_play",
    "app.agents.research", "app.agents.briefing", "app.agents.startup_briefing",
    "app.agents.workspace", "app.agents.focus", "app.agents.meeting_prep",
)


def capability_module_paths(extra_modules: Iterable[str] = ()) -> tuple[str, ...]:
    """Return built-ins plus configured extension modules in stable order."""
    paths: list[str] = []
    for path in (*BUILTIN_CAPABILITY_MODULES, *extra_modules):
        cleaned = path.strip()
        if cleaned and cleaned not in paths:
            paths.append(cleaned)
    return tuple(paths)

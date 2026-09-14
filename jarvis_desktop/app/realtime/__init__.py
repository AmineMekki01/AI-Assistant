"""Realtime conversation components.

The session facade remains available from ``app.core.realtime_session`` during
the migration. New Realtime collaborators live in this package.
"""

from .configuration import RealtimeSessionConfiguration
from .tool_dispatcher import RealtimeToolDispatcher

__all__ = ["RealtimeSessionConfiguration", "RealtimeToolDispatcher"]

"""Core module for JARVIS Desktop.

``RealtimeSession`` is intentionally NOT eagerly re-exported here: it imports
the runtime registry which imports this package's ``logging`` module, and the
eager round-trip produces a circular import. Consumers import it directly via
``from app.core.realtime_session import RealtimeSession``.
"""
from .config import Settings, get_settings
from .logging import StructuredLog, get_logger

__all__ = ['Settings', 'get_settings', 'StructuredLog', 'get_logger']

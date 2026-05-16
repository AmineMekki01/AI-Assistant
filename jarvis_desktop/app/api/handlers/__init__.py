"""
API handlers organized by domain.
"""

from .health import handle_health, handle_dashboard_health
from .system import handle_system_metrics
from .google import handle_google_status, handle_google_disconnect, handle_oauth_callback, handle_auth_success
from .zimbra import handle_zimbra_test, handle_zimbra_status
from .apple_calendar import (
    handle_apple_calendar_test,
    handle_apple_calendar_status,
    handle_apple_calendar_list
)
from .storage import (
    handle_qdrant_status,
    handle_qdrant_test,
    handle_obsidian_status,
    handle_obsidian_sync,
    _index_to_qdrant
)
from .settings import handle_save_settings, handle_load_settings
from .speaker import (
    handle_speaker_profile_status,
    handle_speaker_profile_enroll,
    handle_speaker_profile_clear,
)

__all__ = [
    "handle_health",
    "handle_dashboard_health",
    "handle_system_metrics",
    "handle_google_status",
    "handle_google_disconnect",
    "handle_oauth_callback",
    "handle_auth_success",
    "handle_zimbra_test",
    "handle_zimbra_status",
    "handle_apple_calendar_test",
    "handle_apple_calendar_status",
    "handle_apple_calendar_list",
    "handle_qdrant_status",
    "handle_qdrant_test",
    "handle_obsidian_status",
    "handle_obsidian_sync",
    "_index_to_qdrant",
    "handle_save_settings",
    "handle_load_settings",
    "handle_speaker_profile_status",
    "handle_speaker_profile_enroll",
    "handle_speaker_profile_clear",
]

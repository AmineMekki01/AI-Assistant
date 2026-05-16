"""Route registration for HTTP API."""
from . import handlers


def register_routes(app):
    """Register all API routes with the aiohttp app."""

    app.router.add_get('/api/health', handlers.handle_health)
    app.router.add_get('/api/health/dashboard', handlers.handle_dashboard_health)
    app.router.add_get('/api/system/metrics', handlers.handle_system_metrics)

    app.router.add_get('/api/google/status', handlers.handle_google_status)
    app.router.add_post('/api/google/disconnect', handlers.handle_google_disconnect)
    app.router.add_get('/auth/callback', handlers.handle_oauth_callback)
    app.router.add_get('/auth/success', handlers.handle_auth_success)

    app.router.add_post('/api/zimbra/test', handlers.handle_zimbra_test)
    app.router.add_get('/api/zimbra/status', handlers.handle_zimbra_status)

    app.router.add_post('/api/apple_calendar/test', handlers.handle_apple_calendar_test)
    app.router.add_get('/api/apple_calendar/status', handlers.handle_apple_calendar_status)
    app.router.add_get('/api/apple_calendar/calendars', handlers.handle_apple_calendar_list)

    app.router.add_get('/api/qdrant/status', handlers.handle_qdrant_status)
    app.router.add_post('/api/qdrant/test', handlers.handle_qdrant_test)
    app.router.add_get('/api/obsidian/status', handlers.handle_obsidian_status)
    app.router.add_post('/api/obsidian/sync', handlers.handle_obsidian_sync)

    app.router.add_post('/api/settings/save', handlers.handle_save_settings)
    app.router.add_get('/api/settings/load', handlers.handle_load_settings)

    app.router.add_get('/api/speaker/profile', handlers.handle_speaker_profile_status)
    app.router.add_post('/api/speaker/profile/enroll', handlers.handle_speaker_profile_enroll)
    app.router.add_delete('/api/speaker/profile', handlers.handle_speaker_profile_clear)

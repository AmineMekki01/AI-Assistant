"""Health check endpoint."""
from aiohttp import web


async def handle_health(request):
    """Health check endpoint."""
    print(f"💓 [BACKEND] Health check called from {request.remote}")
    return web.json_response({"status": "ok", "service": "jarvis-api"})

"""Google OAuth handlers."""
import os
from pathlib import Path
from aiohttp import web


async def handle_google_status(request):
    """Check if Google OAuth tokens exist."""
    token_path = Path.home() / ".jarvis" / "google_token.json"
    connected = os.path.exists(token_path)

    last_connected = None
    if connected:
        stat = os.stat(token_path)
        last_connected = stat.st_mtime

    print(f"🔐 [BACKEND] Google status check: connected={connected}")

    return web.json_response({
        "connected": connected,
        "lastConnected": last_connected
    })


async def handle_oauth_callback(request):
    """Handle Google OAuth callback - exchange code for tokens."""
    print(f"🔐 [BACKEND] OAuth callback received")

    from ...core.config import get_settings

    settings = get_settings()
    code = request.query.get('code')
    state = request.query.get('state')

    if not code:
        return web.json_response({"error": "No authorization code received"}, status=400)

    print(f"🔐 [BACKEND] Exchanging code for tokens...")

    import aiohttp
    import json

    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": "http://localhost:8001/auth/callback",
        "grant_type": "authorization_code"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(token_url, data=token_data) as response:
            if response.status != 200:
                error_text = await response.text()
                print(f"X [BACKEND] Token exchange failed: {error_text}")
                return web.json_response({"error": "Token exchange failed"}, status=400)

            tokens = await response.json()

    jarvis_dir = Path.home() / ".jarvis"
    jarvis_dir.mkdir(exist_ok=True)

    token_path = jarvis_dir / "google_token.json"
    with open(token_path, 'w') as f:
        json.dump(tokens, f)

    print(f"🔐 [BACKEND] Google OAuth tokens saved successfully")

    raise web.HTTPFound('/auth/success')


async def handle_auth_success(request):
    """Show OAuth success page."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Google Connected - JARVIS</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
            }
            .container {
                text-align: center;
                padding: 2rem;
            }
            .success-icon {
                font-size: 4rem;
                margin-bottom: 1rem;
            }
            h1 {
                font-size: 2rem;
                margin-bottom: 0.5rem;
            }
            p {
                opacity: 0.9;
                margin-bottom: 2rem;
            }
            .btn {
                background: white;
                color: #667eea;
                padding: 0.75rem 1.5rem;
                border-radius: 8px;
                text-decoration: none;
                font-weight: 600;
                display: inline-block;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="success-icon">✅</div>
            <h1>Google Account Connected!</h1>
            <p>Your Gmail and Google Calendar are now linked to JARVIS.</p>
            <a href="/" class="btn">Return to JARVIS</a>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

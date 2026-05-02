"""System metrics endpoint for the desktop status panel."""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlencode

import aiohttp
from aiohttp import web


_WEATHER_CODE_MAP = {
    0: "Clear sky",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Heavy rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with hail",
}


def _read_personal_settings() -> dict:
    settings_path = Path.home() / ".jarvis" / "settings.json"
    if not settings_path.exists():
        return {}

    try:
        data = json.loads(settings_path.read_text())
        if isinstance(data, dict):
            return data.get("personal", {}) or {}
    except Exception:
        pass
    return {}


def _format_location(result: dict, fallback: str) -> str:
    parts = [
        result.get("name"),
        result.get("admin1"),
        result.get("country"),
    ]
    cleaned = [part for part in parts if isinstance(part, str) and part.strip()]
    return ", ".join(cleaned) if cleaned else fallback


def _weather_condition(code: int | None) -> str | None:
    if code is None:
        return None
    return _WEATHER_CODE_MAP.get(code, "Unknown conditions")


async def _geocode_location(session: aiohttp.ClientSession, location: str) -> dict | None:
    params = urlencode({
        "name": location,
        "count": 1,
        "language": "en",
        "format": "json",
    })
    url = f"https://geocoding-api.open-meteo.com/v1/search?{params}"
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as response:
        if response.status != 200:
            return None
        payload = await response.json()

    results = payload.get("results") if isinstance(payload, dict) else None
    if not results:
        return None
    first = results[0]
    return first if isinstance(first, dict) else None


async def _fetch_weather(
    session: aiohttp.ClientSession,
    latitude: float,
    longitude: float,
    temperature_unit: str,
) -> tuple[float | None, int | None]:
    params = urlencode({
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,weather_code",
        "temperature_unit": temperature_unit,
        "timezone": "auto",
    })
    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as response:
        if response.status != 200:
            return None, None
        payload = await response.json()

    current = payload.get("current") if isinstance(payload, dict) else None
    if not isinstance(current, dict):
        return None, None

    temperature = current.get("temperature_2m")
    weather_code = current.get("weather_code")
    if isinstance(temperature, (int, float)):
        temperature = float(temperature)
    else:
        temperature = None
    if isinstance(weather_code, int):
        code_value: int | None = weather_code
    else:
        code_value = None

    return temperature, code_value


async def handle_system_metrics(request):
    """Return a live snapshot of location, weather, and backend timing data."""
    personal = _read_personal_settings()
    location = str(personal.get("defaultLocation", "")).strip()
    temperature_unit = personal.get("preferences", {}).get("temperatureUnit", "celsius")
    normalized_unit = temperature_unit if temperature_unit in {"celsius", "fahrenheit"} else "celsius"

    if not location:
        return web.json_response({
            "service": "jarvis-api",
            "status": "missing_location",
            "location": "Set a default location in Personal settings",
            "temperature": None,
            "temperatureUnit": normalized_unit,
            "condition": None,
            "updatedAt": time.time(),
        })

    try:
        async with aiohttp.ClientSession() as session:
            geocoded = await _geocode_location(session, location)
            if not geocoded:
                return web.json_response({
                    "service": "jarvis-api",
                    "status": "error",
                    "location": location,
                    "temperature": None,
                    "temperatureUnit": normalized_unit,
                    "condition": None,
                    "updatedAt": time.time(),
                })

            temperature, weather_code = await _fetch_weather(
                session,
                float(geocoded.get("latitude", 0.0)),
                float(geocoded.get("longitude", 0.0)),
                normalized_unit,
            )

            return web.json_response({
                "service": "jarvis-api",
                "status": "ok",
                "location": _format_location(geocoded, location),
                "temperature": temperature,
                "temperatureUnit": normalized_unit,
                "condition": _weather_condition(weather_code),
                "updatedAt": time.time(),
            })
    except Exception:
        return web.json_response({
            "service": "jarvis-api",
            "status": "error",
            "location": location,
            "temperature": None,
            "temperatureUnit": normalized_unit,
            "condition": None,
            "updatedAt": time.time(),
        })

"""
API layer - HTTP handlers and route registration for the WebSocket bridge.
"""

from .routes import register_routes

__all__ = ["register_routes"]

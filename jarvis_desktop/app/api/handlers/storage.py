"""Compatibility imports for storage handlers.

New code should import from ``qdrant`` or ``obsidian`` directly. This module is
kept while internal callers and integrations move to those explicit domains.
"""
from . import obsidian, qdrant

probe_qdrant_status = qdrant.probe_qdrant_status
handle_qdrant_test = qdrant.handle_qdrant_test
handle_obsidian_status = obsidian.handle_obsidian_status
handle_obsidian_sync = obsidian.handle_obsidian_sync
_index_to_qdrant = obsidian._index_to_qdrant


async def handle_qdrant_status(request):
    """Retain the legacy monkeypatchable status entry point."""
    return await qdrant.handle_qdrant_status(request, probe=probe_qdrant_status)

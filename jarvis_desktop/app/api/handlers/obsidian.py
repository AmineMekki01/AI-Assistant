"""Obsidian vault indexing and status endpoints."""
from __future__ import annotations

import asyncio
import glob
import json
import os
from pathlib import Path

from aiohttp import web

from ...knowledge.chunking import chunk_markdown
from ...knowledge.indexing import KnowledgeIndexError, index_documents


async def handle_obsidian_status(request):
    """Return the last vault sync result, if one exists."""
    status_path = Path.home() / ".jarvis" / "obsidian_status.json"
    if status_path.exists():
        try:
            return web.json_response(json.loads(status_path.read_text()))
        except Exception:
            pass
    return web.json_response({"synced": False, "lastSync": None, "fileCount": 0})


async def handle_obsidian_sync(request):
    """Scan markdown files in a vault and write their chunks to the configured store."""
    try:
        data = await request.json()
        vault_path = data.get("vaultPath", "")
        auto_sync = data.get("autoSync", False)
        sync_interval = data.get("syncInterval", 60)
        if not vault_path or not os.path.isdir(vault_path):
            return web.json_response({"success": False, "error": f"Invalid vault path: {vault_path}"}, status=400)

        markdown_files = [
            path for path in glob.glob(os.path.join(vault_path, "**/*.md"), recursive=True)
            if not any(part.startswith(".") for part in Path(path).parts)
        ]
        if not markdown_files:
            return web.json_response({"success": True, "totalFiles": 0, "indexed": 0, "qdrantStatus": "No files to index"})

        documents = []
        for file_path in markdown_files:
            try:
                content = Path(file_path).read_text(encoding="utf-8")
                relative_path = os.path.relpath(file_path, vault_path)
                chunks = chunk_markdown(content)
                title = os.path.splitext(os.path.basename(relative_path))[0]
                documents.extend({
                    "id": f"{relative_path}#chunk{chunk.index}",
                    "text": chunk.text,
                    "metadata": {
                        "source": "obsidian", "file": relative_path, "path": relative_path,
                        "title": title, "chunk_index": chunk.index, "total_chunks": len(chunks),
                        "heading_path": chunk.heading_path,
                    },
                } for chunk in chunks)
            except Exception as error:
                print(f"⚠️ [BACKEND] Could not read {file_path}: {error}")

        qdrant_status = await _index_to_qdrant(documents, vault_path)

        status_path = Path.home() / ".jarvis" / "obsidian_status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps({
            "synced": True, "lastSync": asyncio.get_event_loop().time(),
            "fileCount": len(markdown_files), "indexed": len(documents),
            "vaultPath": vault_path, "autoSync": auto_sync, "syncInterval": sync_interval,
        }))
        return web.json_response({
            "success": True, "totalFiles": len(markdown_files),
            "indexed": len(documents), "qdrantStatus": qdrant_status,
        })
    except KnowledgeIndexError as error:
        print(f"X [BACKEND] Obsidian Qdrant sync error: {error}")
        return web.json_response({"success": False, "error": str(error)}, status=503)
    except Exception as error:
        print(f"X [BACKEND] Obsidian sync error: {error}")
        return web.json_response({"success": False, "error": str(error)}, status=500)


async def _index_to_qdrant(documents: list, vault_path: str) -> str:
    """Compatibility entry point for the dedicated knowledge indexer."""
    return await index_documents(documents, vault_path)

"""Qdrant and Obsidian storage handlers."""
import os
import json
import asyncio
from pathlib import Path
from typing import Optional
from aiohttp import web


def _chunk_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    """Split text into roughly chunk_size-character chunks with overlap."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + chunk_size, n)
        if end < n:
            window = text[i:end]
            break_at = max(
                window.rfind("\n\n"),
                window.rfind(". "),
                window.rfind("\n"),
            )
            if break_at > chunk_size // 2:
                end = i + break_at + 1
        chunks.append(text[i:end].strip())
        if end >= n:
            break
        i = max(end - overlap, i + 1)
    return [c for c in chunks if c]


async def handle_qdrant_status(request):
    """Check Qdrant connection status."""
    try:
        from qdrant_client import QdrantClient

        status_path = Path.home() / ".jarvis" / "qdrant_status.json"
        if status_path.exists():
            data = json.loads(status_path.read_text())
            client = QdrantClient(host=data.get("host", "localhost"), port=data.get("port", 6333))
            collections = client.get_collections()
            collection_exists = any(c.name == data.get("collectionName") for c in collections.collections)
            return web.json_response({
                "connected": True,
                "collectionExists": collection_exists
            })
    except Exception:
        pass

    return web.json_response({
        "connected": False,
        "collectionExists": False
    })


async def handle_qdrant_test(request):
    """Test Qdrant connection and save status."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid request"}, status=400)

    host = data.get("host", "localhost")
    port = int(data.get("port", 6333))
    collection_name = data.get("collectionName", "jarvis_knowledge")
    api_key = data.get("apiKey") or None

    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        client = QdrantClient(host=host, port=port, api_key=api_key)
        client.get_collections()

        status_path = Path.home() / ".jarvis" / "qdrant_status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        with open(status_path, 'w') as f:
            json.dump({
                "host": host,
                "port": port,
                "collectionName": collection_name,
                "apiKey": api_key,
            }, f)

        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def handle_obsidian_status(request):
    """Check Obsidian sync status."""
    status_path = Path.home() / ".jarvis" / "obsidian_status.json"
    if status_path.exists():
        try:
            data = json.loads(status_path.read_text())
            return web.json_response(data)
        except Exception:
            pass

    return web.json_response({
        "synced": False,
        "lastSync": None,
        "fileCount": 0
    })


async def handle_obsidian_sync(request):
    """Handle Obsidian vault sync request - scan and index markdown files."""
    print(f"🔔 [BACKEND] Obsidian sync endpoint called")

    try:
        data = await request.json()
        vault_path = data.get("vaultPath", "")
        auto_sync = data.get("autoSync", False)
        sync_interval = data.get("syncInterval", 60)

        if not vault_path or not os.path.isdir(vault_path):
            return web.json_response({
                "success": False,
                "error": f"Invalid vault path: {vault_path}"
            }, status=400)

        import glob

        md_files = glob.glob(os.path.join(vault_path, "**/*.md"), recursive=True)
        md_files = [f for f in md_files if not any(part.startswith('.') for part in Path(f).parts)]

        print(f"📁 [BACKEND] Found {len(md_files)} markdown files in vault")

        if not md_files:
            return web.json_response({
                "success": True,
                "totalFiles": 0,
                "indexed": 0,
                "qdrantStatus": "No files to index"
            })

        documents = []
        for file_path in md_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                rel_path = os.path.relpath(file_path, vault_path)
                chunks = _chunk_text(content)

                title = os.path.splitext(os.path.basename(rel_path))[0]
                for idx, chunk in enumerate(chunks):
                    documents.append({
                        "id": f"{rel_path}#chunk{idx}",
                        "text": chunk,
                        "metadata": {
                            "source": "obsidian",
                            "file": rel_path,
                            "path": rel_path,
                            "title": title,
                            "chunk_index": idx,
                            "total_chunks": len(chunks)
                        }
                    })
            except Exception as e:
                print(f"⚠️  Error reading {file_path}: {e}")

        print(f"📄 [BACKEND] Prepared {len(documents)} chunks for indexing")
        if documents:
            print(f"   Sample doc metadata: {documents[0]['metadata']}")

        from ...core.config import get_settings
        settings = get_settings()
        use_qdrant = settings.qdrant_url is not None

        qdrant_status = "Not configured"
        if use_qdrant:
            qdrant_status = await _index_to_qdrant(documents, vault_path)
        else:
            local_path = Path.home() / ".jarvis" / "obsidian_index.json"
            with open(local_path, 'w') as f:
                json.dump(documents, f)
            qdrant_status = "Saved to local JSON"

        status_path = Path.home() / ".jarvis" / "obsidian_status.json"
        with open(status_path, 'w') as f:
            json.dump({
                "synced": True,
                "lastSync": asyncio.get_event_loop().time(),
                "fileCount": len(md_files),
                "indexed": len(documents),
                "vaultPath": vault_path,
                "autoSync": auto_sync,
                "syncInterval": sync_interval,
            }, f)

        return web.json_response({
            "success": True,
            "totalFiles": len(md_files),
            "indexed": len(documents),
            "qdrantStatus": qdrant_status
        })

    except Exception as e:
        print(f"X [BACKEND] Obsidian sync error: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


async def _index_to_qdrant(documents: list, vault_path: str) -> str:
    """Index documents to Qdrant vector database."""
    try:
        import uuid
        import numpy as np
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct
        from openai import AsyncOpenAI
        from ...core.config import get_settings

        settings = get_settings()
        client = QdrantClient(url=settings.qdrant_url)
        openai = AsyncOpenAI(api_key=settings.openai_api_key)

        COLLECTION_NAME = "obsidian_vault"

        collections = client.get_collections()
        if not any(c.name == COLLECTION_NAME for c in collections.collections):
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
            )

        points = []
        batch_size = 100

        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            texts = [d["text"] for d in batch]

            response = await openai.embeddings.create(
                input=texts,
                model="text-embedding-3-small"
            )
            embeddings = [item.embedding for item in response.data]

            for doc, embedding in zip(batch, embeddings):
                doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"obsidian:{vault_path}:{doc['id']}"))
                content = doc["text"]
                preview = content[:500] + "..." if len(content) > 500 else content
                payload = {
                    "title": doc["metadata"].get("title", ""),
                    "path": doc["metadata"].get("path", ""),
                    "content_preview": preview,
                    "vault": vault_path,
                }
                if len(points) == 0:
                    print(f"   Sample payload keys: {list(payload.keys())}")
                points.append(PointStruct(
                    id=doc_id,
                    vector=embedding,
                    payload=payload
                ))

        if points:
            client.upsert(collection_name=COLLECTION_NAME, points=points)

        return f"Indexed {len(points)} chunks to Qdrant"

    except Exception as e:
        print(f"X Qdrant indexing error: {e}")
        import traceback
        traceback.print_exc()
        return f"error: {e}"

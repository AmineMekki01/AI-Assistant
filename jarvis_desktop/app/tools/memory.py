"""Memory tools - durable facts about the user, stored in Qdrant.

Auto-creates the ``long_term_memory`` collection on first write. Falls back
to ``~/.jarvis/memories.json`` if Qdrant is unreachable so the feature still
works locally without a running vector DB.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

import httpx
from openai import OpenAI

from ..runtime import tool
from ..memory.retrieval import smart_recall, format_memories_for_context


MEMORY_COLLECTION = os.getenv("QDRANT_MEMORY_COLLECTION", "long_term_memory")
EMBED_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
EMBED_DIM = 1536

ALLOWED_CATEGORIES = {"identity", "preference", "relationship", "goal", "schedule", "other"}


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def _qdrant_url() -> str:
    return os.getenv("QDRANT_URL", "http://localhost:6333")


def _user_id() -> str:
    return os.getenv("JARVIS_USER_ID", "user")


def _embed(text: str) -> List[float]:
    resp = _get_client().embeddings.create(model=EMBED_MODEL, input=text)
    return resp.data[0].embedding


async def _ensure_collection(http: httpx.AsyncClient) -> None:
    check = await http.get(
        f"{_qdrant_url()}/collections/{MEMORY_COLLECTION}", timeout=5.0,
    )
    if check.status_code == 200:
        return
    create = await http.put(
        f"{_qdrant_url()}/collections/{MEMORY_COLLECTION}",
        json={"vectors": {"size": EMBED_DIM, "distance": "Cosine"}},
        timeout=10.0,
    )
    create.raise_for_status()


def _point_id(content: str) -> str:
    seed = f"{_user_id()}|{content}|{datetime.now().astimezone().isoformat()}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def _local_path() -> Path:
    return Path.home() / ".jarvis" / "memories.json"


def _local_store(content: str, category: str) -> None:
    path = _local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    memories: list[dict] = []
    if path.exists():
        try:
            memories = json.loads(path.read_text()) or []
        except Exception:
            memories = []
    memories.append({
        "content": content,
        "category": category,
        "timestamp": datetime.now().astimezone().isoformat(),
    })
    path.write_text(json.dumps(memories, indent=2))


def _local_all() -> List[str]:
    path = _local_path()
    if not path.exists():
        return []
    try:
        memories = json.loads(path.read_text()) or []
    except Exception:
        return []
    return [m.get("content", "") for m in memories if m.get("content")]


def _local_recall(query: str) -> List[str]:
    query_words = {w for w in query.lower().split() if w}
    if not query_words:
        return []
    results: List[str] = []
    for content in _local_all():
        low = content.lower()
        if any(w in low for w in query_words):
            results.append(content)
    return results[-10:]


def _truncate(s: str, n: int = 100) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + "…"

@tool(
    name="memory_remember",
    description="Persist a durable fact about the user (preferences, goals, relationships).",
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Fact to remember"},
            "category": {
                "type": "string",
                "enum": ["identity", "preference", "relationship", "goal", "schedule", "other"],
            },
        },
        "required": ["content", "category"],
    },
)
async def memory_remember(content: str, category: str = "other") -> str:
    if not content:
        return "Error: content is required."
    if category not in ALLOWED_CATEGORIES:
        category = "other"

    try:
        vector = _embed(content)
        async with httpx.AsyncClient() as http:
            await _ensure_collection(http)
            now_iso = datetime.now().astimezone().isoformat()
            point = {
                "id": _point_id(content),
                "vector": vector,
                "payload": {
                    "content": content,
                    "category": category,
                    "user_id": _user_id(),
                    "timestamp": now_iso,
                },
            }
            resp = await http.put(
                f"{_qdrant_url()}/collections/{MEMORY_COLLECTION}/points",
                json={"points": [point]},
                timeout=15.0,
            )
            resp.raise_for_status()
        return f"✓ Remembered [{category}]: {_truncate(content)}"
    except Exception as e: 
        _local_store(content, category)
        return f"✓ Saved locally [{category}] (Qdrant unreachable: {e}): {_truncate(content)}"


@tool(
    name="memory_recall",
    description="Look up relevant facts about the user by semantic query. Uses intelligent ranking based on query type (identity, preference, relationship, goal, schedule).",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Query to search memories"},
            "top_k": {"type": "integer", "description": "Number of memories to return (1-20, default 5)"},
        },
        "required": ["query"],
    },
)
async def memory_recall(query: str, top_k: int = 5) -> str:
    """Smart memory recall with dynamic thresholds and ranking."""
    if not query:
        return "Error: query is required."

    top = max(1, min(int(top_k or 5), 20))

    try:
        memories, status = await smart_recall(query, top_k=top)

        if not memories:
            if "No memories" in status:
                return "No memories stored yet."
            return "No relevant memories found."

        lines = [f"Relevant memories ({status}):"]
        for i, m in enumerate(memories, 1):
            confidence_marker = ""
            if m.raw_similarity < 0.5:
                confidence_marker = " (uncertain)"
            elif m.raw_similarity < 0.6:
                confidence_marker = " (possibly)"

            lines.append(f"{i}. [{m.category}]{confidence_marker} {m.content}")

        return "\n".join(lines)

    except Exception as e:
        matches = _local_recall(query)
        if matches:
            return "Local memories:\n" + "\n".join(f"- {m}" for m in matches[:5])
        return f"Could not retrieve memories: {e}"

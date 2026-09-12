"""Asynchronous Qdrant-backed long-term memory.

Qdrant is the only durable store. A memory tool call validates and queues work;
embeddings, duplicate consolidation, and the upsert run on a bounded background
worker so voice responses never wait on OpenAI embeddings or the vector database.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List

import httpx
from openai import OpenAI

from ..core.logging import StructuredLog
from ..memory.retrieval import smart_recall
from ..runtime import tool

log = StructuredLog(__name__)
MEMORY_COLLECTION = os.getenv("QDRANT_MEMORY_COLLECTION", "long_term_memory")
EMBED_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
EMBED_DIM = 1536
SEMANTIC_MERGE_THRESHOLD = 0.96
QUEUE_SIZE = 64
ALLOWED_CATEGORIES = {"identity", "preference", "relationship", "goal", "schedule", "other"}
DEFAULT_IMPORTANCE = {"identity": 0.95, "relationship": 0.90, "preference": 0.75, "goal": 0.80, "schedule": 0.70, "other": 0.50}
_client: OpenAI | None = None
_queue: asyncio.Queue["MemoryWrite"] | None = None
_workers: set[asyncio.Task] = set()
_queue_lock: asyncio.Lock | None = None


@dataclass(frozen=True)
class MemoryWrite:
    content: str
    category: str
    importance: float
    tags: tuple[str, ...]
    user_id: str


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(timeout=8.0, max_retries=0)
    return _client


def _qdrant_url() -> str:
    return os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/")


def _user_id() -> str:
    return os.getenv("JARVIS_USER_ID", "user")


def _normalize(content: str) -> str:
    return " ".join((content or "").casefold().split())


def _point_id(content: str, user_id: str | None = None) -> str:
    owner = user_id or _user_id()
    digest = hashlib.sha256(f"{owner}|{_normalize(content)}".encode()).hexdigest()
    return str(uuid.UUID(digest[:32]))


def _embed(content: str) -> List[float]:
    response = _get_client().embeddings.create(model=EMBED_MODEL, input=content)
    return response.data[0].embedding


def _importance(value: Any, category: str) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = DEFAULT_IMPORTANCE.get(category, 0.5)
    return max(0.0, min(1.0, score))


async def _ensure_collection(http: httpx.AsyncClient) -> None:
    response = await http.get(f"{_qdrant_url()}/collections/{MEMORY_COLLECTION}", timeout=5)
    if response.status_code == 200:
        return
    if response.status_code != 404:
        response.raise_for_status()
    created = await http.put(f"{_qdrant_url()}/collections/{MEMORY_COLLECTION}", json={"vectors": {"size": EMBED_DIM, "distance": "Cosine"}}, timeout=10)
    if created.status_code != 409:
        created.raise_for_status()


async def _find_semantic_duplicate(http: httpx.AsyncClient, vector: list[float], owner: str) -> dict | None:
    response = await http.post(f"{_qdrant_url()}/collections/{MEMORY_COLLECTION}/points/search", json={
        "vector": vector, "limit": 1, "with_payload": True,
        "filter": {"must": [{"key": "user_id", "match": {"value": owner}}]},
    }, timeout=8)
    if response.status_code in (404, 400):
        return None
    response.raise_for_status()
    hits = response.json().get("result", []) or []
    return hits[0] if hits and float(hits[0].get("score", 0)) >= SEMANTIC_MERGE_THRESHOLD else None


async def _write_memory(item: MemoryWrite) -> None:
    vector = await asyncio.to_thread(_embed, item.content)
    now = datetime.now(timezone.utc).isoformat()
    point_id = _point_id(item.content, item.user_id)
    payload = {"content": item.content, "category": item.category, "user_id": item.user_id,
               "importance": item.importance, "tags": list(item.tags), "status": "open",
               "timestamp": now, "created_at": now, "updated_at": now,
               "last_accessed_at": now, "access_count": 0}
    async with httpx.AsyncClient() as http:
        await _ensure_collection(http)
        duplicate = await _find_semantic_duplicate(http, vector, item.user_id)
        if duplicate and str(duplicate.get("id")) != point_id:
            old = duplicate.get("payload") or {}
            point_id = str(duplicate["id"])
            payload["content"] = max((old.get("content", ""), item.content), key=len)
            payload["importance"] = max(float(old.get("importance", 0.0)), item.importance)
            payload["tags"] = sorted(set((old.get("tags") or []) + list(item.tags)))
            payload["created_at"] = old.get("created_at", now)
            payload["access_count"] = int(old.get("access_count", 0))
        response = await http.put(f"{_qdrant_url()}/collections/{MEMORY_COLLECTION}/points?wait=true", json={"points": [{"id": point_id, "vector": vector, "payload": payload}]}, timeout=10)
        response.raise_for_status()


async def _worker() -> None:
    assert _queue is not None
    while True:
        item = await _queue.get()
        try:
            for attempt in range(3):
                try:
                    await _write_memory(item)
                    log.info("memory.persisted", category=item.category, importance=item.importance)
                    break
                except Exception as error:
                    if attempt == 2:
                        log.error("memory.persist_failed", error=str(error), content_preview=item.content[:80])
                    else:
                        await asyncio.sleep(2 ** attempt)
        finally:
            _queue.task_done()


async def start_memory_writer() -> None:
    global _queue, _queue_lock
    if _queue is None:
        _queue = asyncio.Queue(maxsize=QUEUE_SIZE)
    if _queue_lock is None:
        _queue_lock = asyncio.Lock()
    async with _queue_lock:
        if not _workers or all(task.done() for task in _workers):
            task = asyncio.create_task(_worker())
            try:
                _workers.add(task)
                task.add_done_callback(_workers.discard)
            except (TypeError, AttributeError):
                pass


async def stop_memory_writer() -> None:
    global _queue, _queue_lock
    tasks = list(_workers)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _workers.clear()
    _queue = None
    _queue_lock = None


async def memory_remember(content: str, category: str = "other", importance: float | None = None, tags: list[str] | None = None) -> str:
    content = " ".join((content or "").split()).strip()
    if not content:
        return "Error: content is required."
    category = category if category in ALLOWED_CATEGORIES else "other"
    score = _importance(importance, category)
    item = MemoryWrite(content, category, score, tuple(sorted(set(tags or []))), _user_id())
    await start_memory_writer()
    assert _queue is not None
    try:
        _queue.put_nowait(item)
    except asyncio.QueueFull:
        return "Memory queue is full; nothing was stored."
    return f"✓ Memory queued [{category}, importance {score:.2f}]: {content[:100]}"


async def sync_pending_memories(limit: int = 20) -> int:
    await start_memory_writer()
    return 0


@tool(name="memory_remember", description="Queue a durable user fact for asynchronous Qdrant storage. Exact repeats are idempotent; importance is 0-1 and defaults by category.", parameters={
    "type": "object", "properties": {"content": {"type": "string"}, "category": {"type": "string", "enum": sorted(ALLOWED_CATEGORIES)}, "importance": {"type": "number"}, "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["content", "category"]})
async def memory_remember_tool(content: str, category: str = "other", importance: float | None = None, tags: list[str] | None = None) -> str:
    return await memory_remember(content, category, importance, tags)


@tool(name="memory_recall", description="Recall relevant durable user facts from Qdrant using semantic relevance, category, importance, and recency.", parameters={
    "type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}}, "required": ["query"]})
async def memory_recall(query: str, top_k: int = 5) -> str:
    if not query or not query.strip():
        return "Error: query is required."
    try:
        memories, status = await smart_recall(query, top_k=max(1, min(int(top_k or 5), 20)))
    except Exception as error:
        log.error("memory.recall_failed", error=str(error))
        return "Memory service is temporarily unavailable."
    if not memories:
        return "No relevant memories found in Qdrant."
    lines = [f"Relevant memories ({status}):"]
    for i, m in enumerate(memories, 1):
        similarity = float(getattr(m, "raw_similarity", 1.0))
        marker = " (uncertain)" if similarity < 0.5 else " (possibly)" if similarity < 0.6 else ""
        lines.append(f"{i}. [{m.category}; importance {getattr(m, 'importance', 0.5):.2f}]{marker} {m.content}")
    return "\n".join(lines)

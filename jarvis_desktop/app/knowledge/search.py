"""Hybrid dense + BM25 search over the JARVIS knowledge collection."""
from __future__ import annotations

import asyncio
from typing import Any

from openai import AsyncOpenAI

from .schema import (
    BM25_MODEL,
    BM25_VECTOR_NAME,
    DENSE_VECTOR_NAME,
    collection_name,
    embedding_model,
    qdrant_client_options,
)


_openai_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI()
    return _openai_client


async def _embed_query(query: str, model: str) -> list[float]:
    response = await _get_openai_client().embeddings.create(model=model, input=query)
    return response.data[0].embedding


def _query_points(settings, dense_vector: list[float], query: str, top_k: int) -> list[dict[str, Any]]:
    from qdrant_client import QdrantClient, models

    client = QdrantClient(**qdrant_client_options(settings))
    name = collection_name(settings)
    try:
        response = client.query_points(
            collection_name=name,
            prefetch=[
                models.Prefetch(query=dense_vector, using=DENSE_VECTOR_NAME, limit=max(top_k * 4, 20)),
                models.Prefetch(
                    query=models.Document(text=query, model=BM25_MODEL),
                    using=BM25_VECTOR_NAME,
                    limit=max(top_k * 4, 20),
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as error:
        message = str(error)
        if "not found" in message.lower() or "404" in message:
            raise RuntimeError(
                f"Qdrant collection '{name}' was not found. Open Settings -> Integrations -> Obsidian and click Sync."
            ) from error
        raise
    return [
        {"id": str(point.id), "score": point.score, "payload": point.payload or {}}
        for point in response.points
    ]


async def search_knowledge(query: str, top_k: int = 5, *, settings=None) -> list[dict[str, Any]]:
    """Fuse semantic and exact-term rankings with reciprocal-rank fusion."""
    if settings is None:
        from ..core.config import get_settings

        settings = get_settings()
    if not getattr(settings, "qdrant_url", None):
        raise RuntimeError("Qdrant is not configured. Set QDRANT_URL and start the Qdrant service.")
    dense_vector = await _embed_query(query, embedding_model(settings))
    return await asyncio.to_thread(_query_points, settings, dense_vector, query, max(1, min(int(top_k), 20)))

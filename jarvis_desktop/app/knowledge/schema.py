"""Qdrant schema shared by knowledge indexing and querying."""
from __future__ import annotations

DEFAULT_COLLECTION = "obsidian_vault_hybrid"
DENSE_VECTOR_NAME = "dense"
BM25_VECTOR_NAME = "bm25"
BM25_MODEL = "qdrant/bm25"
EMBEDDING_DIMENSIONS = 1_536


def collection_name(settings) -> str:
    return getattr(settings, "qdrant_vault_collection", DEFAULT_COLLECTION)


def embedding_model(settings) -> str:
    return getattr(settings, "openai_embedding_model", "text-embedding-3-small")


def qdrant_client_options(settings) -> dict[str, object]:
    """Return common Qdrant connection options without exposing secrets."""
    options: dict[str, object] = {
        "url": getattr(settings, "qdrant_url", None),
        "cloud_inference": True,
    }
    api_key = getattr(settings, "qdrant_api_key", "")
    if api_key:
        options["api_key"] = api_key
    return options

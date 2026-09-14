from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from app.knowledge import search


def test_hybrid_query_uses_named_dense_and_bm25_vectors(monkeypatch):
    class FakeClient:
        last_instance = None

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            FakeClient.last_instance = self

        def query_points(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(points=[SimpleNamespace(id="chunk-1", score=0.8, payload={"title": "Atlas"})])

    class FakeDocument:
        def __init__(self, text, model):
            self.text = text
            self.model = model

    qdrant_module = types.ModuleType("qdrant_client")
    qdrant_module.QdrantClient = FakeClient
    models_module = types.SimpleNamespace(
        Document=FakeDocument,
        Prefetch=lambda **kwargs: kwargs,
        FusionQuery=lambda **kwargs: kwargs,
        Fusion=SimpleNamespace(RRF="rrf"),
    )
    qdrant_module.models = models_module
    monkeypatch.setitem(sys.modules, "qdrant_client", qdrant_module)

    settings = SimpleNamespace(
        qdrant_url="http://qdrant.test",
        qdrant_api_key="",
        qdrant_vault_collection="notes_hybrid",
    )
    results = search._query_points(settings, [0.1, 0.2], "project atlas", 3)

    assert results == [{"id": "chunk-1", "score": 0.8, "payload": {"title": "Atlas"}}]
    client = FakeClient.last_instance
    assert client.kwargs["cloud_inference"] is True
    request = client.calls[0]
    assert request["query"] == {"fusion": "rrf"}
    assert request["prefetch"][0]["using"] == "dense"
    assert request["prefetch"][1]["using"] == "bm25"
    assert request["prefetch"][1]["query"].text == "project atlas"
    assert request["prefetch"][1]["query"].model == "qdrant/bm25"

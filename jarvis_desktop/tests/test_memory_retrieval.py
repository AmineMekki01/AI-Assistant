from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.memory import retrieval


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"result": []}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")

    def json(self):
        return self._payload


class FakeHTTPClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, timeout=None):
        self.calls.append((url, json, timeout))
        return self.response


class FakeEmbeddings:
    def __init__(self):
        self.calls = []

    def create(self, model, input):
        self.calls.append({"model": model, "input": input})
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])


class FakeClient:
    def __init__(self):
        self.embeddings = FakeEmbeddings()


def test_query_type_and_threshold_helpers():
    assert retrieval._detect_query_type("who am I?") == "identity"
    assert retrieval._detect_query_type("my wife and family") == "relationship"
    assert retrieval._detect_query_type("what do I like") == "preference"
    assert retrieval._detect_query_type("my goal this year") == "goal"
    assert retrieval._detect_query_type("my schedule tomorrow") == "schedule"
    assert retrieval._detect_query_type("something else") == "general"

    assert retrieval._get_dynamic_threshold("identity") == 0.3
    assert round(retrieval._get_dynamic_threshold("schedule"), 2) == 0.40
    assert round(retrieval._get_dynamic_threshold("general"), 2) == 0.40


def test_expand_query_and_recency_and_formatting():
    expanded = retrieval._expand_query("my wife and travel plans")
    assert "my wife and travel plans" in expanded
    assert any("spouse" in q for q in expanded)

    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert retrieval._calculate_recency_boost(recent) <= 1.0
    assert retrieval._calculate_recency_boost(future) == 1.0
    assert retrieval._calculate_recency_boost("bad timestamp") == 0.7

    hits = [
        {"payload": {"category": "identity", "content": "I am Amine", "timestamp": recent}, "score": 0.9, "id": "1"},
        {"payload": {"category": "goal", "content": "Ship tests", "timestamp": recent}, "score": 0.7, "id": "2"},
    ]
    ranked = retrieval._rank_memories(hits, "identity", retrieval.QUERY_TYPE_WEIGHTS["identity"])
    assert ranked[0].content == "I am Amine"
    assert ranked[0].score >= ranked[1].score

    context = retrieval.format_memories_for_context(
        [
            retrieval.MemoryHit(content="Alpha", category="goal", timestamp="", score=0.6, raw_similarity=0.4, qdrant_id="1"),
            retrieval.MemoryHit(content="Beta", category="other", timestamp="", score=0.5, raw_similarity=0.7, qdrant_id="2"),
        ],
        max_length=120,
    )
    assert "What I know about the user:" in context
    assert "(possibly)" in context

    long_context = retrieval.format_memories_for_context(
        [retrieval.MemoryHit(content="A" * 200, category="other", timestamp="", score=0.5, raw_similarity=0.6, qdrant_id="1")],
        max_length=80,
    )
    assert long_context.endswith("\n...")


@pytest.mark.asyncio
async def test_smart_recall_uses_qdrant_and_local_fallback(temp_home, monkeypatch):
    assert await retrieval.smart_recall("   ") == ([], "No query provided")

    fake_client = FakeClient()
    monkeypatch.setattr(retrieval, "_get_client", lambda: fake_client)
    monkeypatch.setattr(retrieval, "_qdrant_url", lambda: "http://qdrant.test")
    monkeypatch.setattr(retrieval, "_user_id", lambda: "user-123")

    response = FakeResponse(
        200,
        {
            "result": [
                {
                    "id": "one",
                    "score": 0.9,
                    "payload": {
                        "content": "Remember to test",
                        "category": "goal",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(retrieval.httpx, "AsyncClient", lambda *args, **kwargs: FakeHTTPClient(response))

    hits, status = await retrieval.smart_recall("my goal")
    assert hits
    assert status.startswith("Found") or status.startswith("Low confidence")
    assert fake_client.embeddings.calls

    empty_response = FakeResponse(500, {"result": []})
    monkeypatch.setattr(retrieval.httpx, "AsyncClient", lambda *args, **kwargs: FakeHTTPClient(empty_response))
    memories_file = temp_home / ".jarvis" / "memories.json"
    memories_file.parent.mkdir(parents=True, exist_ok=True)
    memories_file.write_text(
        json.dumps(
            [
                {"content": "My goal is to ship tests", "category": "goal", "timestamp": "2026-05-01T10:00:00+00:00"},
                {"content": "Buy groceries", "category": "other", "timestamp": "2026-05-01T10:00:00+00:00"},
            ]
        )
    )
    hits, status = await retrieval.smart_recall("goal tests")
    assert status == "Local memories (Qdrant unavailable)"
    assert hits and hits[0].content == "My goal is to ship tests"

    assert retrieval.should_prime_memory("tell me about my project") is True
    assert retrieval.should_prime_memory("weather tomorrow") is False


@pytest.mark.asyncio
async def test_local_smart_recall_reports_no_memories(temp_home):
    assert await retrieval._local_smart_recall("goal", 3) == ([], "No memories stored yet")

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.tools import knowledge, memory


class FakeMemoryEmbeddings:
    def __init__(self, vector=None):
        self.vector = vector or [0.1, 0.2]
        self.calls = []

    def create(self, model, input):
        self.calls.append({"model": model, "input": input})
        return SimpleNamespace(data=[SimpleNamespace(embedding=self.vector)])


class FakeMemoryClient:
    def __init__(self, vector=None):
        self.embeddings = FakeMemoryEmbeddings(vector)


class FakeMemoryHTTPClient:
    def __init__(self, fail_on_points: bool = False, get_status: int = 200):
        self.calls = []
        self.fail_on_points = fail_on_points
        self.get_status = get_status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, timeout=None):
        self.calls.append(("get", url, timeout))
        return SimpleNamespace(status_code=self.get_status)

    async def put(self, url, json=None, timeout=None):
        self.calls.append(("put", url, json, timeout))
        if self.fail_on_points and url.endswith("/points"):
            raise RuntimeError("qdrant down")
        return SimpleNamespace(raise_for_status=lambda: None)


class FakeKnowledgeEmbeddings:
    def __init__(self, vector=None):
        self.vector = vector or [0.3, 0.4]
        self.calls = []

    async def create(self, model, input):
        self.calls.append({"model": model, "input": input})
        return SimpleNamespace(data=[SimpleNamespace(embedding=self.vector)])


class FakeKnowledgeChatCompletions:
    def __init__(self, answer: str):
        self.answer = answer
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.answer))]
        )


class FakeKnowledgeClient:
    def __init__(self, answer: str = "Synthesised answer"):
        self.embeddings = FakeKnowledgeEmbeddings()
        self.chat = SimpleNamespace(completions=FakeKnowledgeChatCompletions(answer))


class FakeKnowledgeHTTPResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")

    def json(self):
        return self._payload


class FakeKnowledgeHTTPClient:
    def __init__(self, response: FakeKnowledgeHTTPResponse):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, timeout=None):
        self.calls.append((url, json, timeout))
        return self.response


@pytest.mark.asyncio
async def test_memory_remember_success_and_normalizes_category(monkeypatch):
    client = FakeMemoryHTTPClient(get_status=404)
    fake_openai = FakeMemoryClient([0.1, 0.2])

    monkeypatch.setattr(memory, "_get_client", lambda: fake_openai)
    monkeypatch.setattr(memory.httpx, "AsyncClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(memory, "_qdrant_url", lambda: "http://qdrant.test")
    monkeypatch.setattr(memory, "_user_id", lambda: "user-123")

    result = await memory.memory_remember("Testing remembers things", category="invalid")

    assert result.startswith("✓ Remembered [other]:")
    assert client.calls[0][0] == "get"
    assert client.calls[1][0] == "put"
    assert client.calls[2][0] == "put"
    assert client.calls[2][2]["points"][0]["payload"]["category"] == "other"
    assert fake_openai.embeddings.calls[0]["input"] == "Testing remembers things"


@pytest.mark.asyncio
async def test_memory_remember_falls_back_to_local_store(temp_home, monkeypatch):
    client = FakeMemoryHTTPClient(fail_on_points=True)
    fake_openai = FakeMemoryClient([0.9, 0.8])

    monkeypatch.setattr(memory, "_get_client", lambda: fake_openai)
    monkeypatch.setattr(memory.httpx, "AsyncClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(memory, "_qdrant_url", lambda: "http://qdrant.test")
    monkeypatch.setattr(memory, "_user_id", lambda: "user-123")

    result = await memory.memory_remember("Offline fact", category="goal")

    assert result.startswith("✓ Saved locally [goal]")
    memories_file = temp_home / ".jarvis" / "memories.json"
    stored = json.loads(memories_file.read_text())
    assert stored[-1]["content"] == "Offline fact"
    assert stored[-1]["category"] == "goal"


@pytest.mark.asyncio
async def test_memory_recall_variants_and_local_fallback(temp_home, monkeypatch):
    assert await memory.memory_recall("") == "Error: query is required."

    async def no_memories(query, top_k=5):
        return [], "No memories stored yet"

    monkeypatch.setattr(memory, "smart_recall", no_memories)
    assert await memory.memory_recall("who am i") == "No memories stored yet."

    async def no_relevant(query, top_k=5):
        return [], "Nothing matched"

    monkeypatch.setattr(memory, "smart_recall", no_relevant)
    assert await memory.memory_recall("who am i") == "No relevant memories found."

    hits = [
        SimpleNamespace(content="I like dark mode", category="preference", raw_similarity=0.4),
        SimpleNamespace(content="Meeting at 10", category="schedule", raw_similarity=0.55),
    ]

    async def with_hits(query, top_k=5):
        return hits, "Found 2 relevant memories"

    monkeypatch.setattr(memory, "smart_recall", with_hits)
    formatted = await memory.memory_recall("my schedule")
    assert "Relevant memories (Found 2 relevant memories):" in formatted
    assert "(uncertain)" in formatted
    assert "(possibly)" in formatted

    memories_file = temp_home / ".jarvis" / "memories.json"
    memories_file.parent.mkdir(parents=True, exist_ok=True)
    memories_file.write_text(
        json.dumps(
            [
                {
                    "content": "Project alpha is due Friday",
                    "category": "goal",
                    "timestamp": "2026-05-01T08:00:00+00:00",
                },
                {
                    "content": "Lunch with Sam",
                    "category": "other",
                    "timestamp": "2026-05-01T08:05:00+00:00",
                },
            ]
        )
    )

    async def failing_recall(query, top_k=5):
        raise RuntimeError("qdrant unavailable")

    monkeypatch.setattr(memory, "smart_recall", failing_recall)
    local = await memory.memory_recall("project")
    assert local.startswith("Local memories:")
    assert "Project alpha is due Friday" in local


@pytest.mark.asyncio
async def test_knowledge_search_ask_and_list_branches(monkeypatch):
    assert await knowledge.knowledge_search("") == "Please provide a search query."
    assert await knowledge.knowledge_ask("") == "Please provide a question."

    fake_client = FakeKnowledgeClient(answer="Use the notes and act.")
    monkeypatch.setattr(knowledge, "_get_client", lambda: fake_client)

    async def search_hits(vector, top_k):
        return [
            {
                "payload": {
                    "title": "Project Note",
                    "text": "A" * 250,
                },
                "score": 0.88,
            }
        ]

    monkeypatch.setattr(knowledge, "_qdrant_search", search_hits)
    search_text = await knowledge.knowledge_search("project", top_k=3)
    assert "Found 1 matching chunk(s):" in search_text
    assert "📄 Project Note" in search_text

    async def search_runtime_error(vector, top_k):
        raise RuntimeError("index missing")

    monkeypatch.setattr(knowledge, "_qdrant_search", search_runtime_error)
    assert "Error: index missing" in await knowledge.knowledge_search("project")

    async def no_hits(vector, top_k):
        return []

    monkeypatch.setattr(knowledge, "_qdrant_search", no_hits)
    assert (
        await knowledge.knowledge_ask("project")
        == "I couldn't find anything in your Obsidian vault about 'project'."
    )

    async def ask_hits(vector, top_k):
        return [
            {
                "payload": {
                    "title": "Project Alpha",
                    "text": "Use Qdrant for note lookup.",
                },
                "score": 0.4,
            },
            {
                "payload": {
                    "path": "notes/ops.md",
                    "content_preview": "Ops details here.",
                },
                "score": 0.2,
            },
        ]

    monkeypatch.setattr(knowledge, "_qdrant_search", ask_hits)
    answer = await knowledge.knowledge_ask("what about project")
    assert "Use the notes and act." in answer
    assert "Sources: 📄 Project Alpha, 📄 notes/ops.md" in answer

    empty_client = FakeKnowledgeHTTPClient(FakeKnowledgeHTTPResponse(404, {}))
    monkeypatch.setattr(knowledge.httpx, "AsyncClient", lambda *args, **kwargs: empty_client)
    assert "Obsidian index is empty" in await knowledge.knowledge_list()

    success_client = FakeKnowledgeHTTPClient(
        FakeKnowledgeHTTPResponse(
            200,
            {
                "result": {
                    "points": [
                        {"payload": {"path": "notes/a.md", "title": "Note A"}},
                        {"payload": {"file": "notes/b.md", "title": "Note B"}},
                        {"payload": {"path": "notes/a.md", "title": "Note A duplicate"}},
                    ]
                }
            },
        )
    )
    monkeypatch.setattr(knowledge.httpx, "AsyncClient", lambda *args, **kwargs: success_client)
    listed = await knowledge.knowledge_list()
    assert "2 note(s) indexed:" in listed
    assert "📄 Note A" in listed
    assert "📄 Note B" in listed

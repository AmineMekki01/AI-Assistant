from __future__ import annotations

import json
import sys
import types

import pytest

from app.memory import extractor


class FakeLLMCompletions:
    def __init__(self, payload: str | None = None, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content=self.payload or "{}")
                )
            ]
        )


class FakeOpenAIClient:
    def __init__(self, payload: str | None = None, error: Exception | None = None):
        self.chat = types.SimpleNamespace(completions=FakeLLMCompletions(payload, error))


@pytest.mark.asyncio
async def test_memory_extractor_helpers_and_pattern_branches():
    candidate = extractor.MemoryCandidate(
        content="  hello world!  ",
        category="invalid",
        confidence=3.2,
        source="pattern",
        excerpt="hello world",
    )
    assert candidate.category == "other"
    assert candidate.confidence == 1.0

    assert extractor._clean_content("  remember this!!  ") == "Remember this"
    assert extractor._is_excluded("What time is it?") is True
    assert extractor._is_excluded("today I run") is True
    assert extractor._is_excluded("short") is True
    assert extractor._is_excluded("I love coffee") is False

    deduped = extractor.extract_sync("My name is Amine. My name is Amine.")
    assert len(deduped) == 1
    assert deduped[0].content == "User is Amine"
    assert deduped[0].category == "identity"

    transcript = (
        "My wife is Emma. My name is Amine. I'm a backend engineer at Acme. I love coffee and I prefer tea over water. "
        "I want to ship tests by Friday. Every Monday I review inbox at 9."
    )
    patterns = extractor.extract_sync(transcript)
    assert [c.category for c in patterns] == ["relationship", "identity", "identity", "preference", "preference", "goal", "schedule"]
    assert any(c.content == "User's wife is named Emma" for c in patterns)
    assert any(c.content == "User is backend engineer" for c in patterns)
    assert any(c.content == "User is Amine" for c in patterns)
    assert any(c.content == "User loves coffee" for c in patterns)
    assert any(c.content == "User prefers tea" for c in patterns)
    assert any(c.content == "User wants to ship tests" for c in patterns)
    assert any(c.content == "User usually review inbox every monday" for c in patterns)

    assert await extractor.extract_memory_candidates("   ") == []


@pytest.mark.asyncio
async def test_extract_memory_candidates_skips_llm_when_disabled_and_uses_llm_when_enabled(monkeypatch):
    monkeypatch.setenv("MEMORY_USE_LLM_EXTRACTION", "false")
    pattern_only = await extractor.extract_memory_candidates("I love coffee and I want to run tests", use_llm=True)
    assert [c.category for c in pattern_only] == ["preference", "goal"]

    llm_payload = json.dumps(
        {
            "memories": [
                {"content": "I am a backend engineer", "category": "identity", "confidence": 0.95},
                {"content": "I like tea", "category": "preference", "confidence": 0.9},
                {"content": "I enjoy hiking", "category": "madeup", "confidence": 0.89},
                {"content": "too weak", "category": "goal", "confidence": 0.2},
            ]
        }
    )
    client = FakeOpenAIClient(llm_payload)
    fake_openai = types.ModuleType("openai")
    fake_openai.AsyncOpenAI = lambda *args, **kwargs: client
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setenv("MEMORY_USE_LLM_EXTRACTION", "true")

    combined = await extractor.extract_memory_candidates(
        "I love coffee and I want to run tests",
        use_llm=True,
        llm_threshold=0.8,
    )

    assert [c.confidence for c in combined] == [0.95, 0.9, 0.89, 0.85, 0.75]
    assert combined[0].category == "identity"
    assert combined[2].category == "other"
    assert combined[-1].content == "User wants to run tests"
    assert client.chat.completions.calls[0]["model"] == "gpt-4o-mini"
    assert client.chat.completions.calls[0]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_extract_memory_candidates_recovers_from_llm_helper_errors(monkeypatch):
    async def failing_llm_extract(transcript: str, threshold: float):
        raise RuntimeError("llm unavailable")

    monkeypatch.setenv("MEMORY_USE_LLM_EXTRACTION", "true")
    monkeypatch.setattr(extractor, "_llm_extract", failing_llm_extract)

    results = await extractor.extract_memory_candidates("I love coffee and I want to ship tests", use_llm=True)
    assert [c.content for c in results] == ["User loves coffee", "User wants to ship tests"]


@pytest.mark.asyncio
async def test_llm_extract_handles_client_and_json_errors(monkeypatch):
    failing_client = FakeOpenAIClient(error=RuntimeError("boom"))
    fake_openai = types.ModuleType("openai")
    fake_openai.AsyncOpenAI = lambda *args, **kwargs: failing_client
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    assert await extractor._llm_extract("I love coffee", 0.5) == []

    bad_json_client = FakeOpenAIClient(payload="not-json")
    fake_openai.AsyncOpenAI = lambda *args, **kwargs: bad_json_client
    assert await extractor._llm_extract("I love coffee", 0.5) == []

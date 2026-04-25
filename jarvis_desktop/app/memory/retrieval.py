"""Smart retrieval engine - semantic search with ranking, context, and synthesis."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from openai import OpenAI

from ..core.logging import StructuredLog

log = StructuredLog(__name__)

MEMORY_COLLECTION = os.getenv("QDRANT_MEMORY_COLLECTION", "long_term_memory")
EMBED_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
EMBED_DIM = 1536

_client: Optional[OpenAI] = None


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
    """Generate embedding vector for text."""
    resp = _get_client().embeddings.create(model=EMBED_MODEL, input=text)
    return resp.data[0].embedding


QUERY_TYPE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "identity": {"identity": 1.5, "preference": 1.0, "relationship": 0.8, "goal": 0.5, "schedule": 0.3, "other": 0.5},
    "relationship": {"relationship": 1.5, "identity": 0.8, "preference": 0.6, "goal": 0.4, "schedule": 0.3, "other": 0.4},
    "preference": {"preference": 1.5, "identity": 0.7, "relationship": 0.6, "goal": 0.8, "schedule": 0.4, "other": 0.5},
    "goal": {"goal": 1.5, "identity": 0.8, "preference": 0.9, "relationship": 0.5, "schedule": 0.7, "other": 0.5},
    "schedule": {"schedule": 1.5, "goal": 0.6, "preference": 0.5, "identity": 0.4, "relationship": 0.4, "other": 0.4},
    "general": {"identity": 1.2, "preference": 1.2, "relationship": 1.2, "goal": 1.0, "schedule": 0.8, "other": 0.8},
}


def _detect_query_type(query: str) -> str:
    """Classify query to determine relevance weighting."""
    lower = query.lower()
    
    if any(w in lower for w in ["who am i", "what am i", "my name", "i am"]):
        return "identity"
    if any(w in lower for w in ["my sister", "my brother", "my wife", "my husband", "my boss", "my mom", "my dad", "who is"]):
        return "relationship"
    if any(w in lower for w in ["like", "prefer", "favorite", "hate", "love", "enjoy"]):
        return "preference"
    if any(w in lower for w in ["goal", "want to", "trying to", "learning", "plan to"]):
        return "goal"
    if any(w in lower for w in ["schedule", "usually", "every", "always", "typically", "routine"]):
        return "schedule"
    
    return "general"


def _expand_query(query: str) -> List[str]:
    """Expand query with related terms for better recall."""
    expanded = [query]
    lower = query.lower()
    
    relationship_map = {
        "my wife": ["wife", "spouse"],
        "my husband": ["husband", "spouse"],
        "my sister": ["sister", "sibling"],
        "my brother": ["brother", "sibling"],
        "my mom": ["mother", "mom"],
        "my dad": ["father", "dad"],
        "my boss": ["boss", "manager"],
    }
    
    for phrase, alternatives in relationship_map.items():
        if phrase in lower:
            for alt in alternatives:
                expanded.append(query.lower().replace(phrase, f"my {alt}"))
    
    return list(set(expanded))


@dataclass
class MemoryHit:
    """A scored memory hit with metadata."""
    content: str
    category: str
    timestamp: str
    score: float
    raw_similarity: float
    qdrant_id: str


def _calculate_recency_boost(timestamp_str: str) -> float:
    """Calculate recency boost: newer memories score higher."""
    try:
        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        age_days = (datetime.now().astimezone() - ts).days
        
        if age_days < 0:
            return 1.0
        boost = max(0.5, 1.0 - (age_days / 180))
        return boost
    except Exception:
        return 0.7


def _rank_memories(
    hits: List[Dict[str, Any]],
    query_type: str,
    weights: Dict[str, float],
) -> List[MemoryHit]:
    """Rank and score memories with category weighting and recency."""
    results: List[MemoryHit] = []
    
    for hit in hits:
        payload = hit.get("payload", {}) or {}
        raw_score = hit.get("score", 0)
        category = payload.get("category", "other")
        timestamp = payload.get("timestamp", "")
        
        base = raw_score
        
        cat_weight = weights.get(category, 0.8)
        
        recency = _calculate_recency_boost(timestamp)
        
        final_score = base * cat_weight * recency
        
        results.append(MemoryHit(
            content=payload.get("content", ""),
            category=category,
            timestamp=timestamp,
            score=final_score,
            raw_similarity=raw_score,
            qdrant_id=hit.get("id", ""),
        ))
    
    results.sort(key=lambda x: x.score, reverse=True)
    return results


def _get_dynamic_threshold(query_type: str, base_threshold: float = 0.35) -> float:
    """Get adjusted similarity threshold based on query type."""
    adjustments = {
        "identity": -0.05,
        "relationship": -0.05,
        "preference": 0.0,
        "goal": 0.0,
        "schedule": 0.05,
        "general": 0.05,
    }
    adjustment = adjustments.get(query_type, 0.0)
    return max(0.25, min(0.5, base_threshold + adjustment))


async def smart_recall(
    query: str,
    top_k: int = 5,
    min_confidence: Optional[float] = None,
    include_recent: bool = True,
) -> Tuple[List[MemoryHit], str]:
    """Smart memory retrieval with ranking and synthesis.

    Args:
        query: The search query
        top_k: Number of results to return
        min_confidence: Minimum confidence threshold (auto-calculated if None)
        include_recent: Whether to include recent memories in primer

    Returns:
        Tuple of (ranked_memory_hits, status_message)
    """
    if not query or not query.strip():
        return [], "No query provided"

    query_type = _detect_query_type(query)
    weights = QUERY_TYPE_WEIGHTS.get(query_type, QUERY_TYPE_WEIGHTS["general"])
    threshold = min_confidence or _get_dynamic_threshold(query_type)
    
    log.info(
        "retrieval.smart_recall",
        query=query[:50],
        query_type=query_type,
        threshold=threshold,
    )

    expanded_queries = _expand_query(query)
    
    all_hits: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    
    for q in expanded_queries[:2]:
        try:
            vector = _embed(q)
            async with httpx.AsyncClient() as http:
                resp = await http.post(
                    f"{_qdrant_url()}/collections/{MEMORY_COLLECTION}/points/search",
                    json={
                        "vector": vector,
                        "limit": top_k * 2,
                        "with_payload": True,
                        "filter": {
                            "must": [{"key": "user_id", "match": {"value": _user_id()}}]
                        },
                    },
                    timeout=10.0,
                )
                
                if resp.status_code == 404:
                    return [], "No memories stored yet"
                
                resp.raise_for_status()
                hits = resp.json().get("result", []) or []
                
                for hit in hits:
                    hit_id = hit.get("id")
                    if hit_id and hit_id not in seen_ids:
                        seen_ids.add(hit_id)
                        all_hits.append(hit)
        except Exception as e:
            log.error("retrieval.qdrant_error", error=str(e))
            break

    if not all_hits:
        return await _local_smart_recall(query, top_k)

    ranked = _rank_memories(all_hits, query_type, weights)
    
    filtered = [m for m in ranked if m.raw_similarity >= threshold]
    
    if not filtered:
        return ranked[:top_k], "Low confidence results only"
    
    return filtered[:top_k], f"Found {len(filtered)} relevant memories"


async def _local_smart_recall(query: str, top_k: int) -> Tuple[List[MemoryHit], str]:
    """Fallback to local JSON storage with keyword matching."""
    from pathlib import Path
    import json
    
    path = Path.home() / ".jarvis" / "memories.json"
    if not path.exists():
        return [], "No memories stored yet"
    
    try:
        data = json.loads(path.read_text()) or []
    except Exception:
        return [], "Could not read local memories"
    
    query_words = {w.lower() for w in query.split() if len(w) > 2}
    scored: List[Tuple[dict, float]] = []
    
    for m in data:
        content = m.get("content", "").lower()
        score = sum(1 for w in query_words if w in content) / max(len(query_words), 1)
        if score > 0:
            scored.append((m, score))
    
    scored.sort(key=lambda x: x[1], reverse=True)
    
    hits = [
        MemoryHit(
            content=m.get("content", ""),
            category=m.get("category", "other"),
            timestamp=m.get("timestamp", ""),
            score=s * 0.7,
            raw_similarity=s * 0.7,
            qdrant_id="local",
        )
        for m, s in scored[:top_k]
    ]
    
    return hits, "Local memories (Qdrant unavailable)"


def should_prime_memory(task: str) -> bool:
    """Determine if a task warrants memory priming for agents.

    Args:
        task: The agent task/query

    Returns:
        True if memory context would help answer this task
    """
    if not task:
        return False
    
    lower = task.lower()
    
    personal_markers = ["my ", "me ", "i ", "who am", "what am", "tell me about myself"]
    if any(m in lower for m in personal_markers):
        return True
    
    relationship_terms = ["wife", "husband", "sister", "brother", "boss", "mom", "dad", "mother", "father"]
    if any(f"my {r}" in lower for r in relationship_terms):
        return True
    
    if any(w in lower for w in ["my calendar", "my email", "my meeting", "my project"]):
        return True
    
    return False


def format_memories_for_context(memories: List[MemoryHit], max_length: int = 800) -> str:
    """Format memory hits for injection into agent/system context.

    Args:
        memories: List of MemoryHit objects
        max_length: Maximum characters to return

    Returns:
        Formatted context string
    """
    if not memories:
        return ""
    
    lines = ["What I know about the user:"]
    
    for m in memories:
        confidence_marker = ""
        if m.raw_similarity < 0.5:
            confidence_marker = " (possibly)"
        
        lines.append(f"- [{m.category}]{confidence_marker} {m.content}")
    
    result = "\n".join(lines)
    
    if len(result) > max_length:
        result = result[:max_length].rsplit("\n", 1)[0] + "\n..."
    
    return result

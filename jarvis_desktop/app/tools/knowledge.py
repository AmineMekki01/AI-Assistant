"""Knowledge tools - RAG over the user's Obsidian vault via Qdrant.

Sync is handled by the HTTP endpoint ``POST /api/obsidian/sync`` in
``app/core/websocket_bridge.py`` (chunks, embeds with
``text-embedding-3-small``, upserts into ``obsidian_vault``). These tools are
the query side.
"""

from __future__ import annotations

import os
from typing import List

import httpx
from openai import AsyncOpenAI

from ..runtime import tool


VAULT_COLLECTION = os.getenv("QDRANT_VAULT_COLLECTION", "obsidian_vault")
EMBED_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
UTILITY_MODEL = os.getenv("OPENAI_UTILITY_MODEL", "gpt-5.4-nano")


_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI()
    return _client


def _qdrant_url() -> str:
    return os.getenv("QDRANT_URL", "http://localhost:6333")


async def _embed(text: str) -> List[float]:
    resp = await _get_client().embeddings.create(model=EMBED_MODEL, input=text)
    return resp.data[0].embedding


async def _qdrant_search(vector: List[float], top_k: int) -> list[dict]:
    async with httpx.AsyncClient() as http:
        resp = await http.post(
            f"{_qdrant_url()}/collections/{VAULT_COLLECTION}/points/search",
            json={
                "vector": vector,
                "limit": 20,
                "with_payload": True,
            },
            timeout=15.0,
        )
        if resp.status_code == 404:
            raise RuntimeError(
                f"Qdrant collection '{VAULT_COLLECTION}' not found. "
                "Open Settings -> Integrations -> Obsidian and click Sync."
            )
        resp.raise_for_status()
        return resp.json().get("result", []) or []

@tool(
    name="knowledge_search",
    description="Search the Obsidian vault for specific content.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer"},
        },
        "required": ["query"],
    },
)
async def knowledge_search(query: str, top_k: int = 5) -> str:
    if not query:
        return "Please provide a search query."
    try:
        hits = await _qdrant_search(await _embed(query), int(top_k or 5))
    except RuntimeError as e:
        return f"Error: {e}"
    except Exception as e: 
        return f"Error searching vault: {e}"

    if not hits:
        return f"No notes found matching: '{query}'"

    lines = [f"Found {len(hits)} matching chunk(s):"]
    for i, h in enumerate(hits, 1):
        p = h.get("payload", {}) or {}
        title = p.get("title") or p.get("path") or "(untitled)"
        text = p.get("text") or p.get("content_preview") or ""
        snippet = text.strip().replace("\n", " ")
        if len(snippet) > 220:
            snippet = snippet[:220] + "…"
        score = h.get("score")
        score_str = f" ({score:.2f})" if isinstance(score, (int, float)) else ""
        lines.append(f"{i}. 📄 {title}{score_str}\n   {snippet}")
    return "\n".join(lines)


@tool(
    name="knowledge_ask",
    description="Answer a question using the user's Obsidian vault (RAG search).",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Question to answer from your notes"},
            "top_k": {"type": "integer", "description": "Number of notes to search"},
        },
        "required": ["query"],
    },
)
async def knowledge_ask(query: str, top_k: int = 5) -> str:
    if not query:
        return "Please provide a question."

    top = int(top_k or 5)
    try:
        hits = await _qdrant_search(await _embed(query), top)
    except RuntimeError as e:
        return f"Error: {e}"
    except Exception as e: 
        return f"Error searching vault: {e}"

    if not hits:
        return f"I couldn't find anything in your Obsidian vault about '{query}'."

    hits = [h for h in hits if (h.get("score") or 0) >= 0.15] or hits[:top]

    context_blocks = []
    sources: list[str] = []
    for h in hits[:top]:
        p = h.get("payload", {}) or {}
        title = p.get("title") or p.get("path") or "(untitled)"
        content = p.get("text") or p.get("content_preview") or ""
        text = content.strip()
        context_blocks.append(f"# {title}\n{text}")
        if title not in sources:
            sources.append(title)

    context = "\n\n---\n\n".join(context_blocks)[:8000]

    system = (
        "You answer questions using only the provided Obsidian notes. "
        "If the notes don't contain the answer, say you don't know. "
        "Be concise (1-3 sentences) and cite the note title inline when useful.\n\n"
        f"NOTES:\n{context}"
    )

    try:
        resp = await _get_client().chat.completions.create(
            model=UTILITY_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": query},
            ],
            max_completion_tokens=400,
        )
        answer = (resp.choices[0].message.content or "").strip()
    except Exception as e: 
        return f"Error synthesising answer: {e}"

    src_line = "Sources: " + ", ".join(f"📄 {s}" for s in sources[:3])
    return f"{answer}\n\n{src_line}" if answer else f"(no answer generated)\n\n{src_line}"


@tool(
    name="knowledge_list",
    description="List all notes in the Obsidian vault.",
    parameters={"type": "object", "properties": {}, "required": []},
)
async def knowledge_list() -> str:
    async with httpx.AsyncClient() as http:
        resp = await http.post(
            f"{_qdrant_url()}/collections/{VAULT_COLLECTION}/points/scroll",
            json={"limit": 256, "with_payload": True, "with_vector": False},
            timeout=15.0,
        )
        if resp.status_code == 404:
            return (
                "Obsidian index is empty. Open Settings -> Integrations -> Obsidian "
                "and click Sync to index your vault."
            )
        try:
            resp.raise_for_status()
        except Exception as e: 
            return f"Error listing notes: {e}"
        points = resp.json().get("result", {}).get("points", []) or []

    seen: dict[str, str] = {}
    for pt in points:
        p = pt.get("payload", {}) or {}
        path = p.get("path") or p.get("file") or "(untitled)"
        title = p.get("title") or p.get("path") or path
        seen[path] = title
    if not seen:
        return "No notes indexed yet. Run the Obsidian sync from Settings."
    titles = [f"📄 {t}" for t in list(seen.values())[:30]]
    more = "" if len(seen) <= 30 else f"\n… and {len(seen) - 30} more"
    return f"{len(seen)} note(s) indexed:\n" + "\n".join(titles) + more

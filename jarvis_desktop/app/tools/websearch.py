"""Web search tool - Tavily-backed."""

from __future__ import annotations

import os

import httpx

from ..runtime import tool


TAVILY_BASE_URL = "https://api.tavily.com"


@tool(
    name="web_search",
    description="Search the web with Tavily and return summarised results.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {
                "type": "integer",
                "description": "Max results to return (1-10).",
            },
        },
        "required": ["query"],
    },
)
async def web_search(query: str, max_results: int = 5) -> str:
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        return "Error: Tavily API key not configured."

    limit = max(1, min(int(max_results or 5), 10))
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{TAVILY_BASE_URL}/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": limit,
                    "search_depth": "basic",
                    "include_answer": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e: 
        return f"Error searching web: {e}"

    answer = data.get("answer", "")
    results = data.get("results", []) or []

    lines = []
    if answer:
        lines.append(f"Summary: {answer}\n")
    if results:
        lines.append("Sources:")
        for i, r in enumerate(results[:limit], 1):
            title = r.get("title", "Untitled")
            url = r.get("url", "")
            content = (r.get("content") or "")[:200]
            lines.append(f"{i}. {title}")
            lines.append(f"   {content}...")
            if url:
                lines.append(f"   Source: {url}")
            lines.append("")
    return "\n".join(lines) if lines else "No results found."

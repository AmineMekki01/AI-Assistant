"""Auto-extraction service - detect durable facts from user utterances.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple

from ..core.logging import StructuredLog

log = StructuredLog(__name__)

ALLOWED_CATEGORIES: Set[str] = {"identity", "preference", "relationship", "goal", "schedule", "other"}


@dataclass
class MemoryCandidate:
    """A candidate memory extracted from user utterance."""

    content: str
    category: str
    confidence: float
    source: str
    excerpt: str

    def __post_init__(self):
        if self.category not in ALLOWED_CATEGORIES:
            self.category = "other"
        self.confidence = max(0.0, min(1.0, float(self.confidence)))


PATTERNS: List[Tuple[str, re.Pattern, float]] = [
    (
        "relationship",
        re.compile(
            r"my\s+(wife|husband|spouse|boyfriend|girlfriend|partner|fianc[ée])\s+(?:is\s+)?(?:named?\s+)?(\w+)",
            re.IGNORECASE,
        ),
        0.9,
    ),
    (
        "relationship",
        re.compile(
            r"my\s+(sister|brother|sibling|mom|mother|dad|father|parent|boss|manager|colleague|friend)\s+(?:is\s+)?(?:named?\s+)?(\w+)",
            re.IGNORECASE,
        ),
        0.85,
    ),
    (
        "identity",
        re.compile(r"(?:i am|i'm)\s+(?:a\s+)?(\w+(?:\s+\w+){0,3})(?:\s+(?:from|at|in)\b|$)", re.IGNORECASE),
        0.8,
    ),
    (
        "identity",
        re.compile(r"i work as (?:a\s+)?(.+?)(?:\s+(?:at|for|in)\b|$)", re.IGNORECASE),
        0.85,
    ),
    (
        "identity",
        re.compile(r"my name is\s+(\w+(?:\s+\w+)?)", re.IGNORECASE),
        0.95,
    ),
    (
        "preference",
        re.compile(r"i\s+(?:really\s+)?(?:love|like|adore|enjoy)\s+(.+?)(?:\s+(?:and|but|or|when|because)\b|$)", re.IGNORECASE),
        0.85,
    ),
    (
        "preference",
        re.compile(r"i\s+(?:hate|dislike|can't stand|detest)\s+(.+?)(?:\s+(?:and|but|or|when|because)\b|$)", re.IGNORECASE),
        0.85,
    ),
    (
        "preference",
        re.compile(r"i\s+prefer\s+(?:to\s+)?(.+?)(?:\s+(?:over|than|when|because)\b|$)", re.IGNORECASE),
        0.9,
    ),
    (
        "preference",
        re.compile(r"my favorite\s+(.+?)\s+is\s+(.+?)(?:\s+(?:and|but|or|because)\b|$)", re.IGNORECASE),
        0.9,
    ),
    (
        "goal",
        re.compile(r"i want to\s+(.+?)(?:\s+(?:so|because|by|within|before)\b|$)", re.IGNORECASE),
        0.75,
    ),
    (
        "goal",
        re.compile(r"my goal is\s+(?:to\s+)?(.+?)(?:\s+(?:so|because|by|within|before)\b|$)", re.IGNORECASE),
        0.85,
    ),
    (
        "goal",
        re.compile(r"i['']?m\s+(?:trying|attempting|working)\s+to\s+(.+?)(?:\s+(?:so|because|by|within|before)\b|$)", re.IGNORECASE),
        0.8,
    ),
    (
        "goal",
        re.compile(r"i['']?m\s+learning\s+(?:to\s+)?(.+?)(?:\s+(?:so|because|from|with)\b|$)", re.IGNORECASE),
        0.8,
    ),
    (
        "schedule",
        re.compile(r"(?:i\s+)?(?:usually|always|typically|generally)\s+(.+?)(?:\s+(?:on|at|during|except)\b|$)", re.IGNORECASE),
        0.7,
    ),
    (
        "schedule",
        re.compile(r"every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekday|weekend)\s+(?:i\s+)?(.+?)(?:\s+(?:at|unless|except)\b|$)", re.IGNORECASE),
        0.75,
    ),
]

EXCLUSION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b\d{1,2}:\d{2}\b"),
    re.compile(r"\btoday\b|\bnow\b|\bcurrently\b", re.IGNORECASE),
    re.compile(r"\bremind me\b", re.IGNORECASE),
    re.compile(r"\bweather\b", re.IGNORECASE),
]


def _clean_content(raw: str) -> str:
    """Clean extracted content for storage."""
    raw = raw.strip().rstrip(".,!?")
    if raw:
        raw = raw[0].upper() + raw[1:]
    return raw


def _is_excluded(text: str) -> bool:
    """Check if text should be excluded from memory extraction."""
    lower = text.lower()
    if text.strip().endswith("?"):
        return True
    for pattern in EXCLUSION_PATTERNS:
        if pattern.search(text):
            return True
    if len(text.strip()) < 10:
        return True
    return False


def _pattern_extract(transcript: str) -> List[MemoryCandidate]:
    """Extract memory candidates using regex patterns."""
    candidates: List[MemoryCandidate] = []

    if _is_excluded(transcript):
        return candidates

    for category, pattern, confidence_boost in PATTERNS:
        for match in pattern.finditer(transcript):
            groups = match.groups()
            if not groups:
                continue

            if category == "relationship" and len(groups) >= 2:
                relationship = groups[0].lower()
                name = groups[1]
                content = f"User's {relationship} is named {name}"
            elif category == "preference" and len(groups) >= 2:
                domain = groups[0].strip()
                value = groups[1].strip()
                content = f"User's favorite {domain} is {value}"
            elif category == "schedule" and len(groups) >= 2:
                day = groups[0].lower()
                activity = groups[1].strip()
                content = f"User usually {activity} every {day}"
            else:
                content = groups[0].strip()
                if category == "identity":
                    content = f"User is {content}"
                elif category == "preference":
                    content = f"User {match.group(0).lower().split()[1]}s {content}"
                elif category == "goal":
                    content = f"User wants to {content}"

            content = _clean_content(content)
            if len(content) < 5:
                continue

            candidates.append(
                MemoryCandidate(
                    content=content,
                    category=category,
                    confidence=confidence_boost,
                    source="pattern",
                    excerpt=match.group(0),
                )
            )

    return candidates


def _deduplicate(candidates: List[MemoryCandidate]) -> List[MemoryCandidate]:
    """Remove duplicate candidates based on content similarity."""
    seen: Set[str] = set()
    unique: List[MemoryCandidate] = []

    for c in candidates:
        key = c.content.lower().replace(" ", "")
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique


async def extract_memory_candidates(
    transcript: str,
    use_llm: bool = False,
    llm_threshold: float = 0.7,
) -> List[MemoryCandidate]:
    """Extract memory candidates from a user transcript.

    Args:
        transcript: The user's utterance text
        use_llm: Whether to use LLM for additional extraction (slower, more accurate)
        llm_threshold: Confidence threshold for LLM candidates

    Returns:
        List of MemoryCandidate objects sorted by confidence
    """
    if not transcript or not transcript.strip():
        return []

    candidates = _pattern_extract(transcript)

    if use_llm and os.getenv("MEMORY_USE_LLM_EXTRACTION", "false").lower() == "true":
        try:
            llm_candidates = await _llm_extract(transcript, llm_threshold)
            candidates.extend(llm_candidates)
        except Exception as e:
            log.warning("extractor.llm_failed", error=str(e))

    candidates = _deduplicate(candidates)
    candidates.sort(key=lambda c: c.confidence, reverse=True)

    log.info(
        "extractor.candidates_found",
        count=len(candidates),
        transcript_preview=transcript[:50],
    )

    return candidates


async def _llm_extract(transcript: str, threshold: float) -> List[MemoryCandidate]:
    """Use lightweight LLM to extract candidates from complex utterances."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI()
    model = os.getenv("MEMORY_LLM_MODEL", "gpt-4o-mini")

    prompt = f"""Extract any durable facts about the user from this utterance.
Durable facts are: identity, preferences, relationships, goals, recurring schedule patterns.
Do NOT extract: transient info, one-off tasks, current states.

Utterance: "{transcript}"

Respond with JSON array of objects with fields:
- content: the fact to remember (1 sentence, first person converted to third)
- category: one of [identity, preference, relationship, goal, schedule, other]
- confidence: 0.0-1.0

Return empty array [] if no durable facts."""

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You extract durable user facts. Be conservative - only high-confidence facts."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=300,
        )

        content = resp.choices[0].message.content
        import json

        data = json.loads(content)
        candidates = []

        for item in data.get("memories", []):
            conf = float(item.get("confidence", 0))
            if conf >= threshold:
                candidates.append(
                    MemoryCandidate(
                        content=_clean_content(item.get("content", "")),
                        category=item.get("category", "other"),
                        confidence=conf,
                        source="llm",
                        excerpt=transcript[:100],
                    )
                )

        return candidates
    except Exception as e:
        log.error("extractor.llm_error", error=str(e))
        return []


def extract_sync(transcript: str) -> List[MemoryCandidate]:
    """Synchronous wrapper for pattern-based extraction only."""
    if _is_excluded(transcript):
        return []
    candidates = _pattern_extract(transcript)
    return _deduplicate(candidates)

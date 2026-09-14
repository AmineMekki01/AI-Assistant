"""Markdown-aware chunking for knowledge retrieval.

Chunks are formed around headings and paragraph boundaries.  Every chunk keeps
its heading path, so a match from the middle of a long note still carries the
context needed by the model and by a person reading the result.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    """A retrieval-ready section of a source document."""

    text: str
    index: int
    heading_path: tuple[str, ...] = ()


def _normalise(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _split_long_block(block: str, max_chars: int) -> list[str]:
    """Split one unusually long paragraph at sentence or word boundaries."""
    block = block.strip()
    if len(block) <= max_chars:
        return [block] if block else []

    sentences = _SENTENCE_BREAK.split(block)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
        while len(current) > max_chars:
            split_at = current.rfind(" ", 0, max_chars + 1)
            split_at = split_at if split_at > max_chars // 2 else max_chars
            pieces.append(current[:split_at].strip())
            current = current[split_at:].strip()
    if current:
        pieces.append(current)
    return pieces


def _markdown_blocks(text: str) -> list[tuple[tuple[str, ...], str]]:
    """Return paragraph-sized blocks alongside the active Markdown headings."""
    headings: list[str] = []
    blocks: list[tuple[tuple[str, ...], str]] = []
    paragraph: list[str] = []
    in_code_fence = False

    def flush() -> None:
        nonlocal paragraph
        value = "\n".join(paragraph).strip()
        if value:
            blocks.append((tuple(headings), value))
        paragraph = []

    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code_fence = not in_code_fence
            paragraph.append(line)
            continue
        if not in_code_fence:
            match = _HEADING.match(line)
            if match:
                flush()
                level = len(match.group(1))
                heading = match.group(2).strip()
                headings[level - 1:] = [heading]
                continue
            if not line.strip():
                flush()
                continue
        paragraph.append(line)
    flush()
    return blocks


def chunk_markdown(
    text: str,
    *,
    chunk_size: int = 1_200,
    overlap: int = 160,
) -> list[Chunk]:
    """Split Markdown into bounded, contextual chunks.

    ``chunk_size`` is a character budget chosen to remain comfortably below a
    typical embedding input limit.  The short tail of each previous chunk is
    included in the next one, which preserves ideas that cross a paragraph
    boundary without copying entire sections.
    """
    text = _normalise(text)
    if not text:
        return []
    if chunk_size < 200:
        raise ValueError("chunk_size must be at least 200 characters")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    chunks: list[Chunk] = []
    active_heading: tuple[str, ...] = ()
    current: list[str] = []
    current_size = 0
    carry = ""

    def prefix_for(headings: tuple[str, ...]) -> str:
        return " > ".join(headings)

    def flush() -> None:
        nonlocal current, current_size, carry
        body = "\n\n".join(current).strip()
        if not body:
            return
        prefix = prefix_for(active_heading)
        rendered = f"{prefix}\n\n{body}".strip() if prefix else body
        chunks.append(Chunk(text=rendered, index=len(chunks), heading_path=active_heading))
        carry = body[-overlap:].strip() if overlap else ""
        current = []
        current_size = 0

    for headings, block in _markdown_blocks(text):
        # A heading change closes the current section.  It avoids chunks that
        # mix unrelated sections merely because they fit under the size limit.
        if current and headings != active_heading:
            flush()
        active_heading = headings
        heading_size = len(prefix_for(headings)) + (2 if headings else 0)
        for piece in _split_long_block(block, max(200, chunk_size - heading_size)):
            candidate_size = current_size + (2 if current else 0) + len(piece)
            if current and heading_size + candidate_size > chunk_size:
                flush()
                if carry:
                    current = [carry]
                    current_size = len(carry)
            current.append(piece)
            current_size += (2 if current_size else 0) + len(piece)
    flush()

    # Plain text with no blank lines is represented by one block, but this
    # guard makes the public function robust if the parser ever changes.
    return chunks or [Chunk(text=text, index=0)]


def chunk_text(text: str, chunk_size: int = 1_200, overlap: int = 160) -> list[str]:
    """Compatibility-friendly text-only view of :func:`chunk_markdown`."""
    return [chunk.text for chunk in chunk_markdown(text, chunk_size=chunk_size, overlap=overlap)]

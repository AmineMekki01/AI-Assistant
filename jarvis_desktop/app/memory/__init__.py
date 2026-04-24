"""Memory subsystem - intelligent extraction, retrieval, and lifecycle management.

Exports:
    extract_memory_candidates - Pattern-based + LLM extraction from transcripts
    smart_recall - Semantic retrieval with ranking and context
    should_prime_memory - Check if task warrants memory priming

Usage:
    from app.memory import extract_memory_candidates, smart_recall
"""

from .extractor import extract_memory_candidates
from .retrieval import smart_recall, should_prime_memory

__all__ = ["extract_memory_candidates", "smart_recall", "should_prime_memory"]

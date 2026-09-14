"""Knowledge retrieval components for JARVIS.

The package owns document preparation, indexing, and retrieval.  HTTP
handlers and agent tools only coordinate those components.
"""

from .chunking import Chunk, chunk_markdown, chunk_text
from .indexing import KnowledgeIndexError, index_documents
from .search import search_knowledge

__all__ = [
    "Chunk",
    "KnowledgeIndexError",
    "chunk_markdown",
    "chunk_text",
    "index_documents",
    "search_knowledge",
]

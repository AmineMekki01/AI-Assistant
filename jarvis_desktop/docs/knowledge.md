# Knowledge retrieval

JARVIS keeps Obsidian knowledge separate from personal memory. A note sync turns Markdown files into retrieval chunks and writes them to the `obsidian_vault_hybrid` Qdrant collection. No JSON fallback is used: if Qdrant is unavailable, the sync reports the failure instead of pretending the notes are searchable.

## Chunking

`app/knowledge/chunking.py` owns Markdown chunking. It groups content by heading and paragraph, keeps a small overlap when a section needs several chunks, and stores the heading path with each chunk. This makes a result from a long note understandable without loading the whole file.

The API handler only reads vault files and passes prepared documents to the knowledge indexer. It does not decide how text is split.

## Indexing

Each chunk receives two named Qdrant vectors:

- `dense`: an OpenAI `text-embedding-3-small` vector for semantic similarity.
- `bm25`: Qdrant's native sparse BM25 vector for exact names, acronyms, IDs, commands, and other terms where literal matching matters.

Qdrant maintains the corpus-wide IDF statistics for the sparse vector. A sync uses deterministic point IDs and replaces only the current vault's generated points, so re-syncing neither duplicates chunks nor leaves chunks for deleted notes. Indexing runs asynchronously and does not block a conversation turn.

The first hybrid sync creates `obsidian_vault_hybrid`. An existing legacy `obsidian_vault` collection is left unchanged so migration cannot erase it. Run a new Obsidian sync after updating to populate the hybrid collection.

## Searching

For every search, JARVIS sends the query to both named vectors. Qdrant retrieves the leading semantic and BM25 candidates, then combines their ranks with reciprocal-rank fusion (RRF). RRF is a good default because dense cosine scores and BM25 scores are on different scales; it rewards chunks that rank well in either list without treating their raw scores as comparable.

The implementation is in `app/knowledge/search.py`. Agent tools in `app/tools/knowledge.py` only format results or use them as bounded context for an answer.

## Running Qdrant

Use the managed local service from the repository root when developing on this Mac:

```bash
make -C infra up
curl http://localhost:6333/readyz
```

Qdrant 1.16 or newer is required for native BM25 inference. Set `QDRANT_URL` for a remote server and `QDRANT_API_KEY` when that server requires one.

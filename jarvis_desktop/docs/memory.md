# Memory

JARVIS uses Qdrant as its only durable memory store. The collection name
defaults to `long_term_memory`; configure it with
`QDRANT_MEMORY_COLLECTION` when needed. Memories are scoped by
`JARVIS_USER_ID`, which defaults to `user`.

## Write path

`memory_remember` validates a memory and places it on a bounded in-process
queue. It returns as soon as the item is queued. A background worker then:

1. creates an embedding with `OPENAI_EMBEDDING_MODEL`;
2. creates the Qdrant collection if it does not exist;
3. searches the current user's memories for a near duplicate;
4. upserts the memory and its metadata.

The queue holds 64 items. A full queue returns an explicit failure instead of
blocking a voice turn. Each write is retried up to three times with a short
backoff. A persistent failure is logged and is not silently written elsewhere.

## Duplicate handling

Exact duplicates have a stable identifier derived from normalized content and
the user id. Near duplicates use vector similarity. At 0.96 similarity or
higher, JARVIS updates the existing point: it retains the stronger importance,
combines tags, and keeps the longer content. This prevents repeated facts from
filling the collection.

## Memory fields

Each point contains the memory content, category, importance, tags, user id,
creation/update times, last-access time, access count, and status.

Allowed categories are `identity`, `preference`, `relationship`, `goal`,
`schedule`, and `other`. Default importance is higher for identity and
relationships than for general notes.

## Recall path

`memory_recall` embeds the query, searches only the active user's points, then
filters and ranks results. Ranking combines vector similarity with category
weighting, recency, importance, and access history. The query classifier gives
identity, relationship, preference, goal, and schedule questions different
category weights. Weak matches are omitted.

Reading a memory updates its access metadata in a background task. That update
never delays the recall response.

Some delegated agents prime memory before reasoning when the request looks
personal, such as a request about the user's preferences, relationships, or
goals. They receive a small formatted context rather than the whole collection.

## Operating Qdrant

Set `QDRANT_URL` to the server address. Local development normally uses
`http://localhost:6333`.

```bash
docker run --name jarvis-qdrant -p 6333:6333 qdrant/qdrant
curl http://localhost:6333
curl http://localhost:8001/api/qdrant/status
```

The same Qdrant server also holds the Obsidian knowledge collection, whose name
defaults to `obsidian_vault`. The two collections have separate purposes and
should not be mixed.

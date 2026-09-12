# Local JARVIS infrastructure

Start Docker Desktop, then run from the repository root:

```sh
make -C infra up
```

This starts pinned Qdrant 1.17.1, waits for `/readyz`, and creates `long_term_memory`
and `obsidian_vault` with 1536-dimensional cosine vectors and user/timestamp indexes.
The backend's existing `QDRANT_URL=http://localhost:6333` and
`OPENAI_EMBEDDING_MODEL=text-embedding-3-small` defaults match this setup.

```sh
make -C infra status
make -C infra logs
make -C infra down
```

`down` stops the service and preserves both named volumes. `up` reuses them.
Do not run `docker compose down -v` unless you intend to erase the data. Snapshots
live in the separate `qdrant-snapshots` volume. The HTTP and gRPC ports bind only
to localhost; this is a desktop development setup, not a public database deployment.

If an existing Qdrant instance already owns port 6333, keep its data and use
`make -C infra init` to initialize that instance, or stop it before using this
Compose project. Existing collections with a different vector configuration are
reported and left untouched. Existing pre-1.16 Qdrant volumes must follow Qdrant's
sequential upgrade procedure; do not attach them directly to this image.

For custom ports/collections, export the same `QDRANT_URL`, `QDRANT_HTTP_PORT`,
`QDRANT_MEMORY_COLLECTION`, and `QDRANT_VAULT_COLLECTION` values in your shell and
backend configuration. Infrastructure initialization doesn't read API keys or the
backend `.env` file.

Qdrant is the only durable memory store. Memory writes are placed on a bounded
background queue so embeddings and vector upserts never block a voice response.
The worker retries transient failures in memory and reports indexing as pending
if Qdrant is unavailable. Exact repeated facts use a stable per-user point ID;
near-identical facts are consolidated by the worker.

References: [Qdrant installation](https://qdrant.tech/documentation/operations/installation/),
[Qdrant upgrades](https://qdrant.tech/documentation/upgrades/).

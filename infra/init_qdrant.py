"""Wait for Qdrant and idempotently provision JARVIS collections; stdlib only."""
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

URL = os.getenv('QDRANT_URL', f"http://localhost:{os.getenv('QDRANT_HTTP_PORT', '6333')}").rstrip('/')
DIMENSIONS = int(os.getenv('OPENAI_EMBEDDING_DIMENSIONS', '1536'))


def request(path, method='GET', payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(URL + path, data=data, method=method, headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=2) as response:
        raw = response.read()
        try: return json.loads(raw)
        except ValueError: return raw.decode()


def main():
    deadline = time.monotonic() + 60
    while True:
        try:
            request('/readyz')
            break
        except (OSError, URLError):
            if time.monotonic() >= deadline:
                raise SystemExit(f'Qdrant is not ready at {URL}. Run make -C infra logs.')
            time.sleep(1)
    memory_collection = os.getenv('QDRANT_MEMORY_COLLECTION', 'long_term_memory')
    vault_collection = os.getenv('QDRANT_VAULT_COLLECTION', 'obsidian_vault_hybrid')
    collections = (
        (memory_collection, {'vectors': {'size': DIMENSIONS, 'distance': 'Cosine'}},
         [('user_id', 'keyword'), ('timestamp', 'datetime'), ('category', 'keyword'),
          ('status', 'keyword'), ('importance', 'float')]),
        (vault_collection, {
            'vectors': {'dense': {'size': DIMENSIONS, 'distance': 'Cosine'}},
            'sparse_vectors': {'bm25': {'modifier': 'idf'}},
        }, [('vault', 'keyword'), ('path', 'keyword'), ('source', 'keyword')]),
    )
    for name, schema, fields in collections:
        try:
            existing = request(f'/collections/{name}')
            params = existing['result']['config']['params']
            if params.get('vectors') != schema['vectors'] or (params.get('sparse_vectors') or {}) != schema.get('sparse_vectors', {}):
                raise SystemExit(f'{name}: existing vector configuration differs; left untouched.')
        except HTTPError as error:
            if error.code != 404: raise
            request(f'/collections/{name}', 'PUT', schema)
        for field, kind in fields:
            request(f'/collections/{name}/index?wait=true', 'PUT', {'field_name': field, 'field_schema': kind})
        print(f'Ready: {name} ({DIMENSIONS} dimensions, Cosine)')
    print(f'Qdrant ready at {URL}; dashboard: {URL}/dashboard')


if __name__ == '__main__':
    main()

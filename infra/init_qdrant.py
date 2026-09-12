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
    names = (os.getenv('QDRANT_MEMORY_COLLECTION', 'long_term_memory'),
             os.getenv('QDRANT_VAULT_COLLECTION', 'obsidian_vault'))
    for name in names:
        try:
            existing = request(f'/collections/{name}')
            vector = existing['result']['config']['params']['vectors']
            if vector.get('size') != DIMENSIONS or vector.get('distance') != 'Cosine':
                raise SystemExit(f'{name}: existing vector configuration differs; left untouched.')
        except HTTPError as error:
            if error.code != 404: raise
            request(f'/collections/{name}', 'PUT', {'vectors': {'size': DIMENSIONS, 'distance': 'Cosine'}})
        fields = [('user_id', 'keyword'), ('timestamp', 'datetime')]
        if name == os.getenv('QDRANT_MEMORY_COLLECTION', 'long_term_memory'):
            fields += [('category', 'keyword'), ('status', 'keyword'), ('importance', 'float')]
        for field, kind in fields:
            request(f'/collections/{name}/index?wait=true', 'PUT', {'field_name': field, 'field_schema': kind})
        print(f'Ready: {name} ({DIMENSIONS} dimensions, Cosine)')
    print(f'Qdrant ready at {URL}; dashboard: {URL}/dashboard')


if __name__ == '__main__':
    main()

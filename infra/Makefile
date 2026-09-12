.PHONY: up down status logs init
up:
	docker compose up -d
	python3 init_qdrant.py
init:
	python3 init_qdrant.py
status:
	docker compose ps
	curl --fail --silent --show-error http://localhost:$${QDRANT_HTTP_PORT:-6333}/readyz
logs:
	docker compose logs --tail=100 -f qdrant
down:
	docker compose down

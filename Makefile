RUN = uv run --env-file .env
.PHONY: setup up down run test smoke reembed

setup:          ## once
	uv sync
	test -f .env || cp .env.example .env
	mkdir -p data/qdrant data/docs data/tmp

up:             ## start Docker Desktop if needed, then Gotenberg + Qdrant, wait until healthy
	@docker info >/dev/null 2>&1 || (open -ga Docker && until docker info >/dev/null 2>&1; do sleep 2; done)
	docker compose up -d
	curl -sf --retry 30 --retry-all-errors --retry-delay 2 http://127.0.0.1:3100/health >/dev/null
	curl -sf --retry 30 --retry-all-errors --retry-delay 2 http://127.0.0.1:6333/readyz >/dev/null

down:           ## stop containers (frees the Docker VM memory)
	docker compose stop

run: up         ## web app on http://127.0.0.1:8000
	$(RUN) uvicorn app.main:app --host 127.0.0.1 --port 8000

test:           ## unit tests, no network, no Docker
	uv run pytest

smoke: up       ## M0 live checks, ~5 free requests; e.g. make smoke ARGS="--passage-type document"
	$(RUN) python -m app.cli smoke $(ARGS)

reembed:        ## app must be stopped; prints the request estimate and asks first
	$(RUN) python -m app.cli reembed

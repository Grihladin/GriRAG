RUN = uv run --env-file .env
UI = app/frontend
.PHONY: setup up down web run test lint smoke reembed

setup:          ## once
	uv sync
	cd $(UI) && npm ci
	test -f .env || cp .env.example .env
	mkdir -p data/qdrant data/docs data/tmp

up:             ## start Docker Desktop if needed, then Gotenberg + Qdrant, wait until healthy
	@docker info >/dev/null 2>&1 || (open -ga Docker && until docker info >/dev/null 2>&1; do sleep 2; done)
	docker compose up -d
	curl -sf --retry 30 --retry-all-errors --retry-delay 2 http://127.0.0.1:3100/health >/dev/null
	curl -sf --retry 30 --retry-all-errors --retry-delay 2 http://127.0.0.1:6333/readyz >/dev/null

down:           ## stop containers (frees the Docker VM memory)
	docker compose stop

web: $(UI)/dist/index.html    ## build the UI (app/frontend/) if its sources changed

$(UI)/node_modules/.package-lock.json: $(UI)/package-lock.json
	cd $(UI) && npm ci

$(UI)/dist/index.html: $(UI)/node_modules/.package-lock.json $(UI)/index.html $(UI)/vite.config.ts $(shell find $(UI)/src -type f)
	cd $(UI) && npm run build

run: up web     ## web app on http://127.0.0.1:8000
	$(RUN) uvicorn app.backend.main:app --host 127.0.0.1 --port 8000

test:           ## unit tests, no network, no Docker
	uv run pytest

lint:           ## Ruff for the Python code, Oxlint (+ @shadcn/lint) for the UI
	uv run ruff check .
	cd $(UI) && npm run lint

smoke: up       ## M0 live checks, ~5 requests; e.g. make smoke ARGS="--passage-type document"
	$(RUN) python -m app.backend.cli smoke $(ARGS)

reembed:        ## app must be stopped; prints the request estimate and asks first
	$(RUN) python -m app.backend.cli reembed

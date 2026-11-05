UI = app/frontend
# The main checkout, also from a git worktree: docker-compose.yml takes data/ and .env from here,
# so `make up` in a worktree runs that worktree's code on the one library.
export GRIRAG_HOME := $(or $(abspath $(dir $(shell git rev-parse --path-format=absolute --git-common-dir 2>/dev/null))),$(CURDIR))
APP = docker compose run --rm grirag python -m app.backend.cli
.PHONY: up down test lint smoke reembed

up:             ## build and start the app, Gotenberg and Qdrant on http://127.0.0.1:8000 (starts Docker Desktop if needed)
	@test -f $(GRIRAG_HOME)/.env || (echo "No $(GRIRAG_HOME)/.env: cp .env.example .env and put your OPENROUTER_API_KEY in it" && exit 1)
	@docker info >/dev/null 2>&1 || (open -ga Docker && until docker info >/dev/null 2>&1; do sleep 2; done)
	docker compose up -d --build

down:           ## stop everything (frees the Docker VM memory)
	docker compose stop

test:           ## unit tests, no network, no Docker
	uv run pytest

lint: $(UI)/node_modules/.package-lock.json    ## Ruff for the Python code, Oxlint (+ @shadcn/lint) for the UI
	uv run ruff check .
	cd $(UI) && npm run lint

$(UI)/node_modules/.package-lock.json: $(UI)/package-lock.json
	cd $(UI) && npm ci

smoke:          ## live model checks, ~5 requests; e.g. make smoke ARGS="--passage-type document"
	$(APP) smoke $(ARGS)

reembed:        ## stops the app, prints the request estimate and asks first; `make up` afterwards
	docker compose stop grirag
	$(APP) reembed

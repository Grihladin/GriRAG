# AGENTS.md

Instructions for coding agents working in this repository. Read `README.md` for setup, daily use and the
architecture.

GriRAG is a single-user visual RAG. You add PDFs, Word files and web links; every page becomes an image;
the images are embedded through OpenRouter and stored in Qdrant; a vision model answers from the best
pages with citations. Python 3.14 + FastAPI in `app/backend/` (the RAG pipeline in `app/backend/rag/`), React + Vite + Tailwind v4 +
shadcn/ui in `app/frontend/`.

## Commands

- `make test`: unit tests (no network, no Docker). Run them before every commit.
- `make lint`: Ruff for the Python code and `tests/`, Oxlint with `@shadcn/lint` for `app/frontend/`.
- `cd app/frontend && npm run build`: type-check and build the UI.
- `make up`: builds and starts the app, Gotenberg and Qdrant in Docker on http://127.0.0.1:8000. Run it again
  after a code change. `make down` stops everything.

## Commits and pull requests

- Never mention Claude, Anthropic or any AI assistant in commits or pull requests. No `Co-Authored-By`
  trailers for an assistant, and no "Generated with …" lines in PR descriptions. Commits are the user's.
- Commit or push only when asked. Work on a branch, not on `main`.

## Things that break easily

- Start the stack with `make`, not bare `docker compose`: the Makefile sets `GRIRAG_HOME` to the main checkout,
  and Compose takes `data/` and `.env` from there. `make up` in a worktree therefore runs the worktree's code on
  the one library; bare `docker compose up` in a worktree would mount its empty `data/` instead.
- Don't run the app on the host while the container is up: the `flock` on `data/worker.lock` does not reach
  across the Docker bind mount, so both would take it.
- Keep the Qdrant collection name (`pages`): renaming it leaves the stored vectors behind.
- Model calls cost money. Tests never touch the network, and interactive requests are never retried
  automatically.

## UI

- Colours come only from the theme tokens in `app/frontend/src/index.css`, in three roles: graphite for everything
  neutral, the sage `--highlight` as the one accent (and "ready"), and `--destructive` for errors only.
  `shadcn/no-raw-colors` fails the lint on Tailwind palette colours.
- Font: Plus Jakarta Sans (Onest covers Cyrillic). Keep accents muted.
- Never recolour, tint or filter document page images.

## README diagrams

- Sources are `docs/diagrams/*.excalidraw` (open them on excalidraw.com to edit); the README shows PNGs from
  `assets/`, a light and a `-dark` version of each, switched with `<picture>`.
- Render with the official Excalidraw CLI (`npm i -g @excalidraw/cli`), which needs Chrome, Chromium, Edge or
  Firefox (or `EXCALIDRAW_BROWSER_PATH`):
  `excalidraw render docs/diagrams/X.excalidraw --out assets/X.png --scale 2 --transparent`, then again with
  `--theme dark --out assets/X-dark.png`.
- Excalidraw does not resize boxes to their text: make a box wide enough for its label.

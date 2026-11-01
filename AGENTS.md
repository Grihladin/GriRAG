# AGENTS.md

Instructions for coding agents working in this repository. Read `README.md` for setup and daily use and
`PLAN.md` for the design and the decisions behind it.

GriRAG is a single-user visual RAG. You add PDFs, Word files and web links; every page becomes an image;
the images are embedded through OpenRouter and stored in Qdrant; a vision model answers from the best
pages with citations. Python 3.12 + FastAPI in `app/`, React + Vite + Tailwind v4 + shadcn/ui in `web/`.

## Commands

- `make test`: unit tests (no network, no Docker). Run them before every commit.
- `make lint`: Ruff for `app/` and `tests/`, Oxlint with `@shadcn/lint` for `web/`.
- `cd web && npm run build`: type-check and build the UI.
- `make run`: the app on http://127.0.0.1:8000 (starts Docker, Gotenberg and Qdrant).

## Commits and pull requests

- Never mention Claude, Anthropic or any AI assistant in commits or pull requests. No `Co-Authored-By`
  trailers for an assistant, and no "Generated with …" lines in PR descriptions. Commits are the user's.
- Commit or push only when asked. Work on a branch, not on `main`.

## Things that break easily

- Do not run `make up` or `make run` from a git worktree: Docker Compose would remount the shared Qdrant
  container on the worktree's empty `data/qdrant`. In a worktree, start the app with
  `DATA_DIR=<main checkout>/data uv run --env-file .env uvicorn app.main:app --port 8000`.
- The folder, the Compose project (`pixelrag`) and the Qdrant collection keep the old name on purpose.
  Renaming them starts new containers away from the stored vectors.
- Model calls cost money. Tests never touch the network, and interactive requests are never retried
  automatically.

## UI

- Colours come only from the theme tokens in `web/src/index.css`, in three roles: graphite for everything
  neutral, the sage `--highlight` as the one accent (and "ready"), and `--destructive` for errors only.
  `shadcn/no-raw-colors` fails the lint on Tailwind palette colours.
- Font: Plus Jakarta Sans (Onest covers Cyrillic). Keep accents muted.
- Never recolour, tint or filter document page images.

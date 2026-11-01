<img src="assets/icon.svg" width="64" height="64" alt="">

# GriRAG

A local, single-user visual RAG: add PDFs, DOCX files and web links, then search them or ask questions.
Every document becomes page images, the page images are embedded with a vision embedding model, and a
vision LLM answers from the retrieved pages with [S1]–[S3] citations. The approach follows
[PixelRAG](https://github.com/StarTrail-org/PixelRAG) (Apache-2.0); no PixelRAG code is used. The answer
prompt is adapted from PixelRAG's `SYSTEM_PROMPT_EVIDENCE_QA`. See `PLAN.md` for the design.

The app was called PixelRAG until 2026-11-01. The folder, the Docker Compose project (`pixelrag`) and the Qdrant
collection keep their old names: renaming them would recreate the containers away from the stored vectors.

## Setup

Needs uv, Node.js, Docker Desktop (with the default 4 GB VM) and an OpenRouter account with a few dollars of credit.

1. `make setup` creates `.venv`, installs the web UI's packages (`app/frontend/node_modules`), and creates `.env` from
   `.env.example` and `data/`.
2. Put your key from https://openrouter.ai/settings/keys into `.env` as `OPENROUTER_API_KEY`.
3. `make smoke` checks the embedder and the answer model live (5 requests, about $0.01).
4. Only if you switch to `:free` models: on https://openrouter.ai/settings/privacy, enable free endpoints that
   may train on or log inputs, or they answer 404 "no endpoints".

## Daily use

- `make run` starts Docker Desktop if needed, then Gotenberg and Qdrant, rebuilds the web UI (`app/frontend/dist`) if its
  sources changed, then serves the app on http://127.0.0.1:8000.
- **Add** (top bar, or drop files anywhere): PDF/DOCX files and/or http(s) links, one per line. Links to a PDF
  or DOCX file are downloaded; other links are screenshotted at 1120 px wide and cut into 1120 × 1120 pages.
  The top bar (on wider screens) shows what is still processing; the library and each document's page follow it
  live.
- **Ask** (the home page; Enter): sends the question and the 3 best pages to the answer model and shows the
  answer with [S1]–[S3]. Click a citation or thumbnail to see the page large (←/→ for its neighbours); all
  matching pages are listed below the answer. Switch to **Search** to only find pages, without the model. On a
  results page the switch shows the same question in the other mode. `/` focuses the box; Back/Forward go through
  earlier questions.
- The home page also shows the first page of the 24 newest documents. Click a page to open its document.
- **Library:** every document with its status. Type in the filter (or press `/`) to narrow the list by title or
  link; Escape clears it. A document's page (click its title) shows all its pages.
- **Models and settings** (the sliders button in the top bar, labelled with the answer model on wide screens)
  shows the answer model, its temperature and reasoning effort, the embedding model, the page image sizes and
  the limits. It is read-only: change the values in `.env` and restart the app.
- **Retry** a failed or waiting document; **Delete** removes its row, vectors and files. To refresh a web page,
  delete it and add the link again.
- The sun/moon button switches between light and dark; choosing the theme your system uses makes the app follow
  the system again.
- `make down` stops the containers and frees the Docker VM's memory.
- `make reembed` (app stopped) re-embeds everything from the stored page images, after changing `EMBED_MODEL`
  or another embedding setting, or if the Qdrant data was lost. It prints the request count and asks first.
- `make test` runs the unit tests (no network, no Docker).
- `make lint` runs Ruff on the Python code and Oxlint (with `@shadcn/lint`) on `app/frontend/`.

## Web UI development

The UI in `app/frontend/` is React + Vite + TanStack Router/Query + shadcn/ui. It talks to the JSON API under
`/api` in `app/backend/api.py`; FastAPI serves the built `app/frontend/dist` at `/`. The RAG pipeline (convert,
render, embed, vectors, search, answer) is in `app/backend/rag/`.

- Run `make run` in one terminal and `cd app/frontend && npm run dev` in another, then open http://localhost:5173.
  Vite reloads on save and proxies `/api` and `/files` to the app on port 8000.
- `cd app/frontend && npm run build` type-checks and builds; `npx shadcn@latest add <component>` adds a component.
- `cd app/frontend && npm run lint` runs Oxlint with the [`@shadcn/lint`](https://github.com/shadcn-ui/lint) plugin
  registered in `app/frontend/.oxlintrc.json`. `shadcn/no-raw-colors` is on: components use the theme tokens in
  `app/frontend/src/index.css`, not Tailwind palette colours.

## Models and cost

Since 2026-10-30 the app uses paid models (PLAN.md §15): `voyageai/voyage-multimodal-3.5` embeds pages
(about $1 per 1,000 pages, 8 pages per request) and `meta/muse-spark-1.3-contributor` answers (about $0.0001–0.0006 per
question). Each OpenRouter call is logged with its cost (`openrouter /embeddings ... cost=...`).

- A question costs 2 requests (query embedding + answer); asking right after searching the same text costs 1.
- Interactive requests are never retried automatically; click again after an error.
- Balance: https://openrouter.ai/settings/credits. The free-request line on the page and the daily reserve
  (`OR_RESERVE_REQUESTS`) only apply when a `:free` model is configured.
- The free `nvidia/nemotron-3.5-embed-8b:free` still works as a config change (`EMBED_MODEL=...:free`,
  `EMBED_BATCH_PAGES=1`, `EMBED_SQUARE_PAGES=true`, `EMBED_PASSAGE_TYPE=passage`, then `make reembed`), but
  it is slow and unreliable (findings below), and the free tier allows 50 requests/day (1,000/day after
  buying $10 of credits in total).

## Known limitations

- Very tall PDF pages (receipts, chat exports) are not sliced; the library warns that their text may be
  unreadable.
- Long web pages keep only the first 40 pages (44,800 px). Pages too tall for one Chromium capture are
  recaptured with a 44,800 px viewport, which stretches `100vh` sections on some sites.
- Logged-in or paywalled sites index the login or paywall page; intranet/LAN links are blocked.
- Qdrant holds the only copy of the vectors. If `data/qdrant` is lost, the app refuses to start and
  `make reembed` rebuilds it from the page images (about $1 per 1,000 pages).
- No OCR, keyword search, chat history or follow-up questions. Answers use 3 pages, so facts spread over more
  pages can be missed.
- Any website could post a form to http://127.0.0.1:8000 (no auth, no CSRF check). Single-user, local only.

## M0 findings (2026-10-30, free Nemotron 8B embedder)

Measured with `make smoke` and a few one-off probes against the live API.

| Question | Result |
|---|---|
| Images per embedding request | **1.** Any request with 2+ images gets HTTP 502 "service inference failed" from the NVIDIA provider, even two 50 KB pages. Text batches (several questions) work, and one image plus one text input in a request works. `EMBED_BATCH_PAGES=1`: every page costs one request |
| Request size | A single 480 KB photo-like A4 page (0.7 MB request) embeds fine. Vector dim 4096, `index` present |
| Image resolution | An A4 page at 1086 × 1536 costs 1204 prompt tokens and a 1120 × 1120 slice 1644, consistent with the endpoint resizing to a longest edge of 1120 |
| `input_type` | Forwarded and validated: OpenRouter accepts only `query`, `search_query`, `passage`, `document`, `search_document` (anything else is a 400). It changes **text** vectors (query vs none: cos 0.76; passage vs none: cos 0.81) but **not image** vectors (`passage` and `document` both give cos 1.0000 to no mode) |
| Prefix mode | Not possible for pages: a `passage:` text part next to the image in one input gets a 502. `EMBED_INPUT_MODE=field` |
| Retrieval (2 pages) | q1 "capital of Freedonia" picks the web page by +0.31, q2 "invoice total" picks the invoice by +0.38 |
| Answer model | `google/gemma-4-31b-it:free` was "temporarily rate-limited upstream" (429) on every try over ~5 minutes. `nvidia/nemotron-3.5-super-vl:free` answered correctly, including the 7 pt footnote code `K7-334-Q`, with `[S1]`/`[S2]` citations, so `.env` uses it. 1536 px pages are read fine |
| `system` message | Accepted |
| `<think>` in `content` | No; Nemotron Super VL returns reasoning in a separate `reasoning` field (~270 reasoning tokens per answer) |
| Flakiness (M1) | About half of all image requests get a random 502; the same image alternates 200/502. The app retries a 502 up to 3 more times (free: failed requests do not count). On 2026-10-30 16:10–17:55 image embedding was down entirely (OpenRouter showed 0% uptime) |
| Page shapes (M1) | US Letter pages (866 × 1120 after the endpoint's resize) and 852–880 × 1120 fail every time; A4, squares and the other shapes tried work. The app pads every page onto a white square for the embedding request only |
| Quota counter | `GET /key` calls do not count. Failed requests (502, 400, 429) did not count. The counter lags by about one request |

## M2 findings (2026-10-30)

| Question | Result |
|---|---|
| Gotenberg `skipNetworkAlmostIdleEvent=false` | Hangs every screenshot until the 300 s limit, even example.com. Not sent |
| DOCX via LibreOffice | `sample.docx` → 2-page PDF in under 1 s |
| PDF links | `https://arxiv.org/pdf/1706.03762` is downloaded directly (15 pages), no Gotenberg call |
| Web page | Wikipedia "Portable Document Format": 1120 × 28,665 px screenshot in ~14 s → 26 pages, screen layout with backgrounds, no cookie banner, last page shows the footer |
| Blocked URLs | `https://nonexistent.invalid` and `http://host.docker.internal:6333` end in "URL blocked or host not resolvable" |
| Gotenberg stopped | The document stays queued, banner "Worker paused: Gotenberg is not running (make up)", done a minute after `make up` |
| Very long page | "History of the United States" comes back empty from Chromium; the app recaptures the top 44,800 px (40 pages) with `clip=true` and warns. No blank areas seen |

## M3 findings (2026-10-30)

- Search: one embedding request; repeating the same text (or asking it right after) reuses the cached query vector.
- Ask "What is the invoice total?" → "The invoice total is 4,312 EUR [S1]." from `google/gemma-4-31b-it`, with S1 = `sample.pdf` p. 2. A new question costs 2 requests (query embedding + answer), about $0.0001–0.0006 in total.
- Ask "Who won the 1954 World Cup?" (not in the library) → "Not found in the retrieved pages." Gemma followed the evidence-only prompt and did not answer from world knowledge.

## M4 findings (2026-10-30)

- Delete removes the row, the Qdrant points (count 3 → 0) and `data/docs/{id}`. Retry and Delete are hidden
  while a document is being processed; a delete that races the worker is refused ("busy, try again").
- `make reembed` refuses while the app runs ("stop the web app first"); answering `n` changes nothing. A full
  re-embed of the 87-page test library took 14 requests, about 45 s and $0.07; search results were unchanged.

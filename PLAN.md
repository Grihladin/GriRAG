# PLAN.md: Personal visual RAG (PixelRAG approach, OpenRouter free models)

Plan date: 2026-10-30. Target: this repo (`/Users/grihladin/.t3/projects/pixelrag`, branch `main`).
Readers: the developer building it, possibly with a coding agent that works through the milestones in section 10 one at a time.

Conventions in this file:
- **unverified**: not confirmed by docs, source code or a local test.
- **estimate**: arithmetic or published figures, not measured on this machine.
- Upstream PixelRAG references point at the research clone of `main @ cf91bd4` (2026-10-27). Gotenberg references are tag `v8.39.0`.

---

## 1. Goal and scope

**Goal.** A local, single-user app where you add PDFs, DOCX files and web links, then search them or ask questions about them. It follows PixelRAG's approach (github.com/StarTrail-org/PixelRAG, Apache-2.0):
1. Render every document to page images.
2. Embed the page images with a vision embedding model.
3. Retrieve page images for a question.
4. Let a vision LLM read those pages and answer, citing document and page.

**What v1 does**
1. Accepts PDF and DOCX uploads and pasted http(s) links through one small web page.
2. Converts every input with Gotenberg. DOCX goes through Gotenberg's LibreOffice route to PDF, and PDFs pass through unchanged. Web pages become one full-page screenshot, 1120 px wide, from Gotenberg's Chromium screenshot route. Links that point straight at a PDF or DOCX file are downloaded by the app and handled like an upload, not screenshotted.
3. Turns each document into page JPEGs. PyMuPDF renders each PDF page to one JPEG and also cuts a web screenshot into 1120 × 1120 px pages, so it is the only imaging library. One page is one retrieval unit.
4. Embeds the page images with a free OpenRouter embedder (`nvidia/nemotron-3.5-embed-8b:free`). The vectors are stored in Qdrant, and only there.
5. **Search:** embeds the question with the same model and shows the top pages as thumbnails, grouped by document.
6. **Ask:** sends the question and the top 3 page images to a free OpenRouter vision chat model (`google/gemma-4-31b-it:free`). It shows the answer with [S1]–[S3] citations and a Sources row: document, page, and a thumbnail that links to the page image.
7. **Library:** lists each document with its status and progress, with Retry and Delete actions.
8. Stays inside the free tier:
   - each embedding request carries several pages;
   - the app sends at most 20 requests a minute;
   - an ingest job that hits a quota limit waits, then resumes by itself.

**Not in v1:**
- auth or multi-user
- privacy work (out of scope by decision; M0 covers the one account toggle the free models need)
- local ML models or torch
- OCR or text extraction, keyword or hybrid search
- crawling whole sites
- per-site cookies, logins or paywalls
- chat history or follow-up questions
- streaming answers
- re-ingesting or refreshing a document (use Delete, then add it again)
- a backup of the vectors (Later list, open question 6)
- a CLI beyond `smoke` and `reembed`
- file types beyond PDF/DOCX (each is one config entry, untested)
- mobile layout

---

## 2. Decisions

| # | Decision | Why | Rejected / deferred |
|---|---|---|---|
| 1 | Web pages are rendered by **Chromium inside Gotenberg** | Real layout engine, full-page screenshots built in | **Lightpanda**: its screenshots are text-only; it has no layout engine |
| 2 | **PDF and DOCX become PDF; web pages become screenshots; Gotenberg 8.39.0 does both** (one Docker container). DOCX: `POST /forms/libreoffice/convert`. Web page: `POST /forms/chromium/screenshot/url`. PDF: unchanged. A link whose response is a PDF or DOCX file is downloaded by the app with one streamed GET (§5.2) and then handled like an upload | One converter for every input, configured only through env vars. Two short paths: PDF → page JPEGs, screenshot → page slices. Headless Chromium does not show a PDF response as the document: it either aborts it as a download or shows a viewer page (unverified for 8.39.0) | A separate renderer per format. **A separate Chromium/CDP renderer next to Gotenberg** (user decision) |
| 3 | Web pages are **screenshotted, not printed**: one full-page JPEG 1120 px wide (`width=1120`, `clip=false`), then **cut into 1120 × 1120 px pages with PyMuPDF** (§5.3, about 12 lines; no Pillow, so there is one imaging library): top to bottom, no overlap, a last strip under 28 px dropped, the first `MAX_WEB_PAGES` (40) kept. `WEB_VIEWPORT_WIDTH` and `WEB_SLICE_HEIGHT` are config values | Screen layout as you see it: no print CSS, no page-break cuts, no fixed headers repeated on every page. **1120 follows the embedder**: Nemotron 3.5 Embed's processor (PixtralImageProcessor, patch 14, spatial merge 2) resizes every image to a longest edge of 1,120 px, keeping the aspect ratio; the default is 1,120 (up to 1,540) and the model card's benchmarks ran at 1,120 ([model card](https://huggingface.co/nvidia/Nemotron-3.5-Embed-8B-BF16), `processor_config.json`). A 1120 × 1120 slice reaches the embedder at full resolution, with no downscaling. 1120 px is also a normal desktop viewport width. Whether OpenRouter's hosted endpoint uses the default 1,120 is unverified. The slicing idea (rows, no overlap, small remnant dropped) comes from PixelRAG's chunker (`embed/src/pixelrag_embed/chunk.py:48-49`, `:195-197`, `:224-226`) | **Print to PDF via `convert/url`**: the user rejected "everything becomes PDF" for web pages. **PixelRAG's 875 × 1024 tiles**: tuned for its Qwen3-VL-Embedding model, which this app does not use. **One image per whole page**: the embedder shrinks a very tall page until the text is unreadable, and the whole page becomes one vector |
| 4 | **One JPEG per PDF page, rendered with PyMuPDF**: longest edge 1536 px, quality 85 (sizing in §5.4). Web slices are stored at their native 1120 × 1120 | Streams one page at a time, needs no poppler, about 10 lines | PixelRAG `render_pdf`: needs pdf2image and `brew install poppler`, holds every page in RAM (`backends/pdf.py:82`), and its 200 dpi output (1654 × 2339 px for A4) is larger than either API uses |
| 5 | **No dependency on the `pixelrag` package** | Its embedder, index and server go unused. The only useful piece, `render_pdf`, would pull in core deps the app never uses (`cef-capi-py`, `anthropic`, `websockets`, `pyturbojpeg`: `pyproject.toml:17-31`) plus poppler | PyPI `pixelrag==0.4.0`, or a git-pinned `main` |
| 6 | **Models via the OpenRouter API, free models first** (`https://openrouter.ai/api/v1`, key in `OPENROUTER_API_KEY` in an uncommitted `.env`). Each model slug is one config value | The 8 GB Mac cannot run models next to Docker. Free models cost $0. A paid model later is a config change | **Local models**: replaced by the user decision of 2026-10-30 |
| 7 | **Embedder: `nvidia/nemotron-3.5-embed-8b:free`** (**changed 2026-10-30 to paid `voyageai/voyage-multimodal-3.5`, see §15**), cosine. The dimension (4096) is read from the first response, not configured. One model embeds both page images (passage mode) and question text (query mode). The mode goes either in the `input_type` field or, if OpenRouter does not forward that field, as the model card's `query:`/`passage:` text prefixes. M0 measures which works (`EMBED_INPUT_MODE`) | NVIDIA built it for retrieval over document page images: text, tables, charts, infographics ([model card](https://huggingface.co/nvidia/Nemotron-3.5-Embed-8B-BF16)) | `nemotron-3.5-embed-1b:free`: fallback; 2048-d, a different vector space. `llama-nemotron-embed-vl-1b-v2:free`: its OpenRouter page says "trial use only". Qwen3-VL-Embedding-8B: not on OpenRouter, too big to run locally |
| 8 | **PixelRAG's own LoRA-tuned Qwen3-VL-Embedding-2B is NOT used in v1** | It is not on OpenRouter. Checked 2026-10-30: the public `/api/v1/embeddings/models` lists 38 models, none of them Qwen3-VL-Embedding or PixelRAG; the only Qwen embedders are the text-only `qwen/qwen3-embedding-8b`/`-4b`. Running it locally needs torch and about 4.3 GB of bf16 weights | Deferred to "Later" as a swap-in behind the `Embedder` interface (re-embedding required) |
| 9 | **Answer model: `google/gemma-4-31b-it:free`** (**changed 2026-10-30 to paid `google/gemma-4-31b-it`, see §15**) | Free, dense 31B, image input, 262,144-token context, one provider (Google AI Studio). Supported parameters include `max_tokens`, `temperature` and `reasoning` (`/api/v1/models/google/gemma-4-31b-it:free/endpoints`, checked 2026-10-30) | First alternative: `nvidia/nemotron-3.5-super-vl:free`. Upgrade: `qwen/qwen3.8-27b` (paid). Not usable: `openrouter/free` (routes to an arbitrary model), `google/lyria-*` (music), `nvidia/nemotron-3.5-content-safety:free` (classifier) |
| 10 | **Qdrant** (Docker, `localhost:6333`, bind-mounted `data/qdrant`, telemetry off) holds the page vectors, and it is the only copy. **SQLite** holds the catalog and job state in one `documents` table. **Plain folders** under `data/` hold originals, PDFs, web screenshots and page images. The app calls Qdrant itself through `qdrant-client` | Add and delete per document, no rebuilds. This is the approved storage split | **FAISS**: `build_ivf` rebuilds everything and has no add or delete (`embed/src/pixelrag_embed/index.py:143`). **`pixelrag serve`**: reads `articles.json` once at startup (`serve/src/pixelrag_serve/api.py:758-761`). **`build_qdrant`**: reads shard `.npz` files, has no delete, and is missing from the 0.4.0 wheel. **A second copy of every vector as an SQLite BLOB**: a second vector store outside the approved split. Losing Qdrant is handled by `reembed` from the kept JPEGs, or by a snapshot (Later) |
| 11 | **Point id = `doc_id * 10000 + page_no`**, payload `{doc_id, page}`. `documents.id` is AUTOINCREMENT and never reused, and `MAX_PAGES` must stay ≤ 9999. `documents.pages_embedded` is both the progress counter and the resume point | No `pages` table is needed: a page's file is `data/docs/{doc_id}/pages/{page:04d}.jpg`, pages are embedded in order, and re-upserting the same id is idempotent | A `pages` table with a row (and a vector) per page |
| 12 | **Job queue = `documents.status`** (4 states: `queued`, `working`, `done`, `error`) **plus one daemon worker thread** in the app process, guarded by a lock file | No extra service, and it survives restarts. The lock stops a second app instance or `cli reembed` from working on the same data at the same time | Celery, RQ, arq (need Redis); FastAPI `BackgroundTasks` (lost on restart); a separate `jobs` table; a `cli work` process (a second process means a second throttle) |
| 13 | **UI: FastAPI + Jinja2 + vendored htmx 2.0.11** | 4 small templates, no build step, nothing loaded from a CDN | Gradio and Streamlit: usage telemetry on by default, and they pull in pandas and more. NiceGUI: no saving |
| 14 | **Plain `httpx`** for OpenRouter, Gotenberg and link downloads | Direct access to 429 headers and error bodies, no hidden retries | `openai` SDK: retries 429 twice by default, sends `encoding_format=base64` unless told otherwise, and its type hints reject image embedding input |
| 15 | **Three failure outcomes** (§8.4). `RateLimited`: this document waits and resumes by itself. `Paused` (a service is down or the config is wrong): the document stays queued, the whole worker pauses with backoff, and a banner explains why. `DocError` or any other exception: this document goes to `error` and you click Retry | Only quota exhaustion has to resume by itself (decision 5b2). A stopped Docker container must not flip every queued document to `error` | Per-document transient retries with attempt counters and exponential backoff |
| 16 | **Privacy out of scope** (user decision). No `provider` data-policy fields are sent | Accepted: free providers may log or train on inputs | Sending `provider.data_collection="deny"` would rule out the only provider of the free NVIDIA embedders and fail every request |

### What PixelRAG contributes

PixelRAG contributes its **approach** and a few concrete choices. Its model and its code are not used:
- **Pipeline.** Render, embed page images, retrieve pages, let a VLM read them.
- **Slicing idea for web pages.** Cut a tall screenshot into rows top to bottom, with no overlap, and drop a tiny last strip (`embed/src/pixelrag_embed/chunk.py:48-49`, `:195-197`, `:224-226`). The 1120 × 1120 slice size is the app's own, set by its embedder (decision 3).
- **Page unit.** One PDF page = one chunk (`backends/pdf.py:99`, "Each PDF page = one chunk (no further splitting)"). One web slice = one chunk.
- **Reader message shape.** The question text, then one `image_url` data URL per retrieved page, with an evidence-only system prompt (`eval/lib/llm.py:56-59` `SYSTEM_PROMPT_EVIDENCE_QA`, `:317-331`). It uses 3 pages (`eval/run_bench.py:1530-1533`: `--retrieval-top-k` default 3).
- **Wait before capture.** PixelRAG waits for fonts and eager images, capped at 2 s, and deliberately skips lazy images (`strategies/cdp_oneshot.py:42-63`; lazy filter at `:45`, 2000 ms at `:51`). `SCROLL_JS` (§5.2) starts from that idea and goes further, because a single full-page screenshot never gets a second chance to load lazy content.

No PixelRAG code is imported or copied. The app's README credits PixelRAG (Apache-2.0) for the approach and the adapted prompt.

### Trade-offs accepted

- **Not PixelRAG's tuned model.** Retrieval quality comes from a general NVIDIA embedder. PixelRAG's LoRA gains, measured on Wikipedia screenshots, do not carry over.
- **Page images and questions leave the machine.** The free NVIDIA embedder endpoints carry `training: true, retainsPrompts: true` (NVIDIA API Trial Terms, as shown on the OpenRouter model page). Accepted.
- **Free-tier quotas.** 20 requests/minute. 50 requests/day while less than $10 of credits has ever been purchased; 1,000/day after a one-time purchase of ≥ $10 ([limits](https://openrouter.ai/docs/api-reference/limits)). On 50/day, a large backlog takes days.
- **Free models can change or disappear without notice.**
  - Changing the answer model is a config change.
  - Changing the embedding model means re-embedding every page. The page JPEGs are kept, so nothing is re-rendered, but it costs quota. The model id, dim and passage mode are recorded on the Qdrant collection and checked at startup.
- **Qdrant holds the only copy of the vectors.** If the collection is lost, `make reembed` rebuilds it from the kept JPEGs. That costs ceil(pages / 8) requests: 1,000 pages ≈ 125 requests, about 3 days on 50/day. A snapshot backup is on the Later list (open question 6).
- **Prefix mode is an approximation.** If `input_type` is not forwarded, the model card's prefixes go in as text parts. The model card's own code puts them in a system message, which OpenRouter's embedding input cannot express.
- **3 pages per answer.** Facts spread over more pages can be missed.

---

## 3. Architecture

```
                       Browser  http://127.0.0.1:8000
                         │  forms (htmx), <img src="/files/{doc}/pages/NNNN.jpg">
                         ▼
┌──────────────── Python app: one process (uv, Python 3.12) ─────────────────┐
│  main.py  routes, search, ask ──► ingest.add_file / add_url ──► SQLite      │
│     │  /files = static data/docs                          data/app.db       │
│     │                                                          ▲ claim      │
│     │            worker thread (daemon): ingest.worker_loop()  │            │
│     │              convert ──► render ──► embed batch ──► upsert            │
│     ▼                 │           │            │             │              │
│  embedder.py ──► openrouter.py (httpx, 3.2 s slots, quota budget, 429)      │
└───────────────────────┼───────────┼────────────┼─────────────┼──────────────┘
                        ▼           ▼            ▼             ▼
       Gotenberg :3100         PyMuPDF,     OpenRouter      Qdrant :6333
       (Docker: LibreOffice   (slices too)  /embeddings     (Docker) "pages"
        + Chromium), or a     (in-process)  /chat/completions  cosine
        direct download for                 /key (free-quota counter)
        PDF/DOCX links
```

**Components (one job each)**
- **Browser page**: add files and links, see the library, search and ask. Plain HTML plus htmx.
- `app/main.py`: FastAPI routes, plus `search()`, `ask()` and `build_messages()`. The lifespan hook checks the key, takes the worker lock, checks the collection, runs recovery, then starts the worker thread. Serves `data/docs` at `/files`.
- `app/ingest.py`: `add_file`/`add_url` (validate, dedup, enqueue), the worker loop (convert → render → embed → upsert), `retry`, `delete`, `reembed`.
- `app/convert.py`: the direct download for PDF/DOCX links, the two Gotenberg calls with their error mapping, PyMuPDF rendering (one page in memory at a time), and the PyMuPDF slicer for web screenshots.
- `app/openrouter.py`: the only code that talks to OpenRouter. Throttle, free-quota read, 429 classification, chat, error mapping.
- `app/embedder.py`: the `Embedder` interface plus the OpenRouter implementation (pages in passage mode, questions in query mode).
- `app/store.py`: SQLite schema and queries (claim, recover, compare-and-set), plus the Qdrant collection, upsert, grouped search and delete.
- `app/config.py`: settings from env, with defaults.
- `app/cli.py`: `smoke` (M0) and `reembed`.
- `app/__init__.py`: the three exception classes `DocError`, `Paused`, `RateLimited`.
- **Gotenberg (Docker)**: LibreOffice (DOCX → PDF) and Chromium (web page → screenshot), reachable only on 127.0.0.1.
- **Qdrant (Docker)**: vector search over page vectors.
- **OpenRouter (remote)**: embeddings and chat.

**Ingest flow**
```
PDF upload ────────────────────────────────────────────────────────────┐
DOCX upload ─────────────► Gotenberg POST /forms/libreoffice/convert ──┤
URL ─► streamed GET ─► application/pdf ──► download ───────────────────┤
           │        └► DOCX type ──► download ──► LibreOffice route ───┤
           │                                                           ▼
           │                                       data/docs/{id}/doc.pdf
           │                                                           │  PyMuPDF, page by page,
           │                                                           │  longest edge 1536 px
           └► anything else ──► Gotenberg screenshot route             │
              POST /forms/chromium/screenshot/url                      │
                                     │  full-page JPEG, 1120 px wide   │
                                     ▼                                 │
                      data/docs/{id}/source.jpg                        │
                                     │  PyMuPDF: 1120 px rows          │
                                     ▼                                 │
                      data/docs/{id}/pages/0001.jpg, 0002.jpg, ...   ◄─┘
                                     ▼  up to 8 JPEGs per request, passage mode
                      OpenRouter POST /embeddings  →  4096-d vectors
                                     ▼
   Qdrant upsert (id = doc_id*10000 + page, payload {doc_id, page})  →  documents.pages_embedded = n
```

**Query flow**
```
question ─► OpenRouter /embeddings (query mode; cached per text)
         ─► Qdrant query_points_groups(group_by="doc_id", limit=10, group_size=max(ANSWER_PAGES, 3))
         ─► join documents in SQLite (groups without a row are dropped)
         ─► Search: groups ─► thumbnails
         ─► Ask:    3 best pages overall + question ─► OpenRouter /chat/completions
                    ─► answer with [S1]..[S3] + Sources row (document, page, thumbnail)
```

---

## 4. Data model

### 4.1 SQLite (`data/app.db`)

One table. One document is one job.

```sql
PRAGMA journal_mode = WAL;      -- set on every connection, with busy_timeout = 5000

CREATE TABLE IF NOT EXISTS documents (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,  -- never reused: point ids and /files URLs stay unique
  kind            TEXT NOT NULL CHECK (kind IN ('pdf', 'office', 'url')),
  source          TEXT NOT NULL,           -- uploaded file name, or the URL
  title           TEXT NOT NULL,           -- file name, or the URL
  dedup_key       TEXT NOT NULL UNIQUE,    -- 'sha256:<hex of uploaded bytes>' or 'url:<normalized url>'
  status          TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'working', 'done', 'error')),
  message         TEXT,                    -- error text or wait reason, shown in the library
  warning         TEXT,                    -- set at render, e.g. very tall pages or a web page cut at MAX_WEB_PAGES
  next_attempt_at INTEGER,                 -- unix seconds; NULL = as soon as possible
  page_count      INTEGER,                 -- NULL until rendered
  pages_embedded  INTEGER NOT NULL DEFAULT 0  -- pages 1..n are in Qdrant; embedding resumes at n+1
);
```

Notes:
- There is no `pages` table. A page is `(doc_id, page_no)`. Its file is `data/docs/{doc_id}/pages/{page_no:04d}.jpg` and its Qdrant id is `doc_id * 10000 + page_no`.
- "Waiting" is how the library shows a `queued` row whose `next_attempt_at` is in the future. `message` holds the reason.
- Library progress is `pages_embedded / page_count`.
- No vector copy and no `meta` table. The model id, dim and passage mode live on the Qdrant collection (4.2).

### 4.2 Qdrant collection

| Setting | Value |
|---|---|
| Name | `pages` (constant `QDRANT_COLLECTION`) |
| Vectors | `size` = length of the first returned vector (4096 for Nemotron 3.5 Embed 8B), `distance = Cosine`, other settings default |
| Payload | `{"doc_id": int, "page": int}` (page is 1-based) |
| Payload index | `doc_id`, `PayloadSchemaType.INTEGER` (delete by document, grouping) |
| Point id | `doc_id * 10000 + page_no` |
| Collection metadata | `{"embed_model": EMBED_MODEL, "dim": n, "passage_mode": "field:passage" \| "field:document" \| "prefix"}`, passed to `create_collection(metadata=...)` and read back from `get_collection(...).config.metadata` |
| Created | lazily, at the first upsert |

The exact calls with `qdrant-client==1.20.0`. `search()` no longer exists in this client. `query_points_groups` and filter delete were checked in local `:memory:` mode on 2026-10-30:

```python
qc.create_collection("pages", vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
                     metadata={"embed_model": MODEL, "dim": dim, "passage_mode": MODE})
qc.create_payload_index("pages", field_name="doc_id", field_schema=models.PayloadSchemaType.INTEGER)
qc.upsert("pages", points=[models.PointStruct(id=doc_id * 10000 + n, vector=vec,
                                              payload={"doc_id": doc_id, "page": n})], wait=True)
qc.query_points_groups("pages", group_by="doc_id", query=qvec, limit=10, group_size=3,
                       with_payload=True).groups          # each: .id (doc_id), .hits[] with .score .payload
qc.delete("pages", points_selector=models.FilterSelector(filter=models.Filter(
    must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])))
```

**Startup check** (`store.check_collection`, run in the lifespan before the worker starts):
1. If the collection exists and its `embed_model` or `passage_mode` differs from the config, exit with `EMBED_MODEL changed from X to Y: run 'make reembed' (≈ N requests) or revert .env`.
2. If the collection is missing but some document has `pages_embedded > 0`, the Qdrant data was lost. Exit with `Qdrant collection 'pages' is missing but N pages were embedded: run 'make reembed' (≈ M requests)`.
3. Otherwise continue. The collection is created at the first upsert.

Qdrant needs about 16 KB of RAM per page for the vectors (4096 × 4 bytes), plus about 20% headroom ([capacity planning](https://qdrant.tech/documentation/capacity-planning/)). Requests are capped at 32 MB (`config.yaml@v1.20.0:383`); an upsert of 8 points is about 0.3 MB of JSON.

### 4.3 Folders (`data/`, gitignored)

```
data/
  app.db               SQLite (+ app.db-wal, app.db-shm)
  worker.lock          held by the running app (or by cli reembed)
  tmp/                 uploads and downloads in progress
  qdrant/              bind-mounted to /qdrant/storage in the Qdrant container
  docs/
    42/                one folder per document; delete = rm -r this folder
      original.docx    office uploads and DOCX links (kept so Retry can re-convert)
      doc.pdf          PDF and DOCX documents (and PDF/DOCX links): the PDF every page comes from; for PDF uploads it is the upload itself
      source.jpg       web pages only: the full-page Gotenberg screenshot, 1120 px wide, that the pages are cut from
      pages/
        0001.jpg       page 1: a PDF page (longest edge 1536 px) or a web slice (1120 × 1120), JPEG quality 85
        0002.jpg
```

The app serves `data/docs` at `/files`, so `/files/42/pages/0003.jpg` is page 3, and `/files/42/doc.pdf` or `/files/42/source.jpg` is the whole document. Uploaded file names are stored only in `documents.source` and are never used as paths.

---

## 5. Ingest pipeline

### 5.1 Adding (request thread, fast)

`add_file(conn, cfg, filename, fileobj) -> (doc_id, created: bool)` and `add_url(conn, url) -> (doc_id, created)`:

1. **Validate.**
   - Skip multipart parts whose filename is empty. Browsers send one empty part when no file is chosen.
   - The extension, lower-cased, must be `.pdf` or in `OFFICE_EXTENSIONS` (default `{".docx"}`). The content itself is checked later, by PyMuPDF or LibreOffice in the worker; a bad file ends in `error` with a readable message.
   - A URL must parse with scheme `http`/`https` and a host. Strip whitespace and drop the `#fragment`; the query string is kept.
2. **Stream files to `data/tmp/<uuid>`** in 1 MB chunks, computing the sha256 on the way. Stop and reject at `MAX_UPLOAD_MB` (default 200).
3. **Dedup.**
   - Files: `dedup_key = "sha256:" + hex`. The same file under another name counts as a duplicate.
   - URLs: `dedup_key = "url:" + normalized_url`. The screenshot bytes change on every capture, so hashing them would never match.
   - On a match, delete the temp file and return the existing id with `created=False`. The UI then says "already in library as #id (status); delete it first to refresh".
4. **Insert and move, in one transaction.** `INSERT` the row (status `queued`), create `data/docs/{id}/`, `os.replace` the temp file to `doc.pdf` (PDF) or `original.docx` (office), then commit. URLs write no file. If anything fails, roll back and remove the folder and the temp file. If a concurrent duplicate hits the UNIQUE constraint (`IntegrityError`), return the existing row. The worker uses its own connection, so it never sees a half-added document.
5. **Wake the worker** (`threading.Event.set()`).

PyMuPDF is never called in request threads, because it is not thread-safe. Only the worker renders.

### 5.2 Converting (worker, only if neither `doc.pdf` nor `source.jpg` exists)

**Links that are files (kind `url`, tried first).** `convert.fetch_direct` sends one `httpx.stream("GET", url, follow_redirects=True, timeout=30)` and reads only the headers before deciding:
- `application/pdf`, or `application/octet-stream` with a `.pdf` URL path: stream the body to `data/tmp` (capped at `MAX_UPLOAD_MB`) and rename it to `doc.pdf`. Gotenberg is not called.
- `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, or octet-stream with a `.docx` path: save it as `original.docx`, then use the LibreOffice route below.
- Anything else, a non-200 status, or any network error: close the stream and use the screenshot route. The download attempt never fails a document by itself.
- This GET runs on the Mac, not inside Gotenberg, so Gotenberg's private-IP rule does not apply to it. That is acceptable for a single user's own links.

**Gotenberg calls.** Every Gotenberg route requires `multipart/form-data` and returns 415 otherwise (`pkg/modules/api/context.go:236-246`), so `httpx` sends every field through `files=` as `(None, value)`. The `httpx` timeout is 330 s, longer than Gotenberg's `API_TIMEOUT=300s`.

**URL → screenshot:** `POST {GOTENBERG_URL}/forms/chromium/screenshot/url`. The form fields are the module constant `WEB_SHOT`, built from config:

| Field | Value | Note (source: `pkg/modules/chromium/routes.go@v8.39.0`) |
|---|---|---|
| `url` | the normalized URL | required, http/https only (`:576`, `validateUrlScheme`) |
| `width` | `1120` (`WEB_VIEWPORT_WIDTH`) | viewport width in px (`:400`); default 800 |
| `height` | `1120` (`WEB_SLICE_HEIGHT`) | viewport height (`:401`); default 600. With `clip=false` it does not limit the capture; it only sets what `100vh` means and the `SCROLL_JS` step |
| `clip` | `false` | the default (`:402`). `captureScreenshotActionFunc` always sets `WithCaptureBeyondViewport(true)` and clips only when `clip=true` or `selector` is set, so the **whole page** is captured at the given width (`tasks.go:199-222`) |
| `format` | `jpeg` | png, jpeg or webp (`:404-416`); default png |
| `quality` | `85` (`JPEG_QUALITY`) | jpeg only (`:418-438`, `tasks.go:224-227`); default 100 |
| `emulatedMediaType` | `screen` | a common Chromium field (`:264`), shared with the convert routes |
| `skipNetworkAlmostIdleEvent` | `false` | waits until ≤ 2 connections stay open for 500 ms. Both skip fields default to `true` (`:88`) |
| `waitForExpression` | `SCROLL_JS` (below) | form field at `:151`; the Promise is awaited; an expression that throws or returns undefined gives HTTP 400 (`:1079-1085`) |
| *not sent* `failOnHttpStatusCodes` | default `[499,599]` | common field (`:89`); a main page answering 4xx/5xx gives HTTP 409 |
| *not sent* `selector`, `optimizeForSpeed`, `deviceScaleFactor` | defaults (none, `false`, `1.0`) | one image pixel per CSS pixel |

`SCROLL_JS` is a module constant. It switches lazy images to eager and scrolls through the page one viewport (1120 px) at a time, at most 40 steps of 150 ms, so the first 40 × 1120 px (the `MAX_WEB_PAGES` cap) get their lazy content. Then it returns to the top and waits for fonts and images (at most 5 s). It catches every error and always returns true, so it cannot cause the 400. Fixed and sticky elements are left alone: a screenshot shows them once, not on every page:

```js
(async () => { try { document.querySelectorAll('img[loading="lazy"]').forEach((i) => { i.loading = 'eager'; }); const step = window.innerHeight || 800; for (let y = 0, n = 0; y < document.documentElement.scrollHeight && n < 40; y += step, n++) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 150)); } window.scrollTo(0, 0); const pending = Array.from(document.images).filter((i) => !i.complete).map((i) => new Promise((r) => { i.addEventListener('load', r, { once: true }); i.addEventListener('error', r, { once: true }); })); await Promise.race([Promise.all([document.fonts.ready, ...pending]), new Promise((r) => setTimeout(r, 5000))]); } catch (e) {} return true; })()
```

**DOCX → PDF:** `POST {GOTENBERG_URL}/forms/libreoffice/convert` with exactly one field, `files = ("original.docx", bytes)`.
- LibreOffice picks the format from the uploaded filename's extension (`api/formdata.go:578-583`), so the extension must be kept.
- Send one file per request; several files come back as a ZIP.
- Since 8.34.0, linked (external) images in documents are dropped. Embedded ones are kept.

**Response:** PDF bytes (LibreOffice) or JPEG bytes (screenshot). Write them to `doc.pdf.tmp` or `source.jpg.tmp`, then rename to `doc.pdf` or `source.jpg`, so "the file exists" always means complete.

**Gotenberg errors.** Error bodies are plain text and are stored in `documents.message`.

| Status | Meaning (source, v8.39.0) | Outcome |
|---|---|---|
| 400 | bad field; the expression threw; navigation failed ("Chromium returned net::…", `chromium/routes.go:1145-1151`); LibreOffice could not read or convert the file, or it is password-protected (`libreoffice/routes.go:432-463`) | `DocError` with the body text |
| 403 | body is just `Forbidden`. The main URL is checked before Chromium starts (`chromium/browser.go:511-518`). A host that does not resolve, a private address and a deny-list hit all end here (`gotenberg/outbound.go:365-383`, `api/middlewares.go:52-53`) | `DocError("URL blocked or host not resolvable (DNS failure, private address, or deny list)")` |
| 409 | the page itself returned 4xx/5xx | `DocError` |
| 500 | LibreOffice "unattributable failure" (`libreoffice/routes.go:467`), or the screenshot capture itself failed, e.g. a page too tall to capture in one shot (unmapped Chromium error; unverified) | `DocError` |
| 503 | time limit exceeded (`api/middlewares.go:48-49`) or Chromium crashed (`chromium/routes.go:1062-1069`) | `DocError`; Retry helps after a crash |
| 429 | Gotenberg's queue is full (`api/middlewares.go:56-57`) | `Paused` |
| connection refused, `httpx` timeout | Gotenberg not running, or hung | `Paused("Gotenberg is not running: make up")` |

**Title:** URL documents keep the URL as their title. The screenshot carries no page title, and v1 does not parse the HTML for one.

### 5.3 Rendering (worker, only if `page_count IS NULL`)

`process()` picks the path by file: `doc.pdf` goes to `render_pages`, `source.jpg` (web pages) goes to `slice_screenshot`. Both write `pages/0001.jpg, 0002.jpg, ...` and return `(page_count, warning)`.

**PDF pages (PDF uploads, DOCX, PDF/DOCX links):**

```python
def render_pages(pdf: Path, out_dir: Path, *, longest_edge: int, quality: int, max_pages: int
                 ) -> tuple[int, str | None]:                 # (page_count, warning)
    with pymupdf.open(pdf) as doc:                          # open failure -> DocError("not a readable PDF")
        if doc.needs_pass: raise DocError("password-protected PDF")
        if not 0 < doc.page_count <= max_pages: raise DocError(f"{doc.page_count} pages (limit {max_pages})")
        tall = []
        for no, page in enumerate(doc, start=1):            # one page in memory at a time
            w, h = page.rect.width, page.rect.height
            z = longest_edge / max(w, h)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
            pix.save(out_dir / f"{no:04d}.jpg", jpg_quality=quality)   # signature checked on pymupdf 1.27.2.3
            if max(w, h) > 3 * min(w, h): tall.append(no)
        return doc.page_count, (f"pages {tall} are very tall; text may be unreadable" if tall else None)
```

**Web pages (`source.jpg`):** cut the one tall screenshot into `WEB_SLICE_HEIGHT` (1120) px rows, top to bottom, with no overlap. A last strip shorter than 28 px is dropped, and only the first `MAX_WEB_PAGES` (40) slices are kept. The idea comes from PixelRAG's chunker (`embed/src/pixelrag_embed/chunk.py:48-49`, `:195-197`, `:224-226`); the slice size is the app's own (decision 3).

```python
MIN_SLICE_PX = 28

def slice_screenshot(src: Path, out_dir: Path, *, slice_height: int, quality: int, max_pages: int
                     ) -> tuple[int, str | None]:            # (page_count, warning)
    img = pymupdf.Pixmap(str(src))                            # decode failure -> DocError("not a readable screenshot")
    w, h = img.width, img.height
    n = 0
    for y in range(0, h, slice_height):                       # top to bottom, no overlap
        if h - y < MIN_SLICE_PX or n == max_pages: break      # drop a strip under 28 px; keep the first max_pages
        n += 1
        tile = pymupdf.Pixmap(img.colorspace, pymupdf.IRect(0, y, w, min(y + slice_height, h)), img.alpha)
        tile.copy(img, tile.irect)                            # copies the same rectangle out of the screenshot
        tile.set_origin(0, 0)
        tile.save(out_dir / f"{n:04d}.jpg", jpg_quality=quality)
    if n == 0: raise DocError("empty screenshot")
    cut = h - n * slice_height >= MIN_SLICE_PX
    return n, (f"page is {h} px tall; only the first {n} pages are kept" if cut else None)
```

Tested on 2026-10-30 with `pymupdf==1.28.2` (also 1.27.2.3 and 2.0): 1120 × 2300 gives 3 slices (1120, 1120, 60), 1120 × 2250 gives 2, 1120 × 44,800 gives 40, and each slice starts at the right row. PyMuPDF has no decompression-bomb limit to raise, unlike Pillow.

The slicer decodes the whole screenshot at once: 1120 × 44,800 px (40 slices) × 3 bytes ≈ 150 MB. A JPEG cannot be taller than 65,535 px, which caps this at about 220 MB.

After rendering, one `UPDATE` sets `page_count` and `warning`. If the app crashes mid-render, `page_count` stays NULL, and the next run re-renders and overwrites the files. Very tall PDF pages (receipts, chat exports) are not sliced, by decision; the warning makes them visible in the library.

### 5.4 Page image resolution (one JPEG per page serves embedding, answering and display)

Sizing follows the embedder. Nemotron 3.5 Embed resizes every image to a longest edge of 1,120 px by default, keeping the aspect ratio ("the checkpoint's configured longest-edge limit of 1,120 pixels", [model card](https://huggingface.co/nvidia/Nemotron-3.5-Embed-8B-BF16)); `processor_config.json` allows up to 1540. Whether the hosted endpoint uses the same default is unverified.
- **Web slices** are captured at 1120 × 1120 and stored as they are (`WEB_VIEWPORT_WIDTH`, `WEB_SLICE_HEIGHT`), so they reach the embedder at full resolution, with no downscaling.
- **PDF pages** are rendered at **`PAGE_LONGEST_EDGE_PX = 1536`** for the answer model's sake (below). The embedder downsizes them to 1,120 anyway.
- **`JPEG_QUALITY = 85`** for both (PixelRAG's default quality, `backends/pdf.py:22`).

| Page type | PDF page size | Stored JPEG | Effective dpi | Embedder probably sees (1120 px default) |
|---|---|---|---|---|
| Web slice from the Gotenberg screenshot | — (no PDF) | 1120 × 1120 (the last slice 28–1120 px tall) | 1 px per CSS px | 1120 × 1120, unchanged |
| A4 DOCX/PDF | 595 × 842 pt | 1086 × 1536 | 131 | 792 × 1120 |
| US Letter | 612 × 792 pt | 1187 × 1536 | 140 | 866 × 1120 |
| 16:9 slide | 960 × 540 pt | 1536 × 864 | 115 | 1120 × 630 |

The A4 row was measured with PyMuPDF 1.27.2.3 on 2026-10-30. The other rows are arithmetic.

Why 1536 for PDF pages:
- **Embedder.** It sees at most 1,120 px on the longest edge (above). Pixels beyond that are most likely discarded.
- **Answer model.** It has to read small print. At 1536 px, 9 pt text on A4 is about 16 px tall; at the embedder's 1120 px it would be about 12 px. Web body text (16 CSS px) stays 16 px in a web slice. Whether the Gemma provider downscales images is unverified. M0 checks this with a 7 pt footnote; if that fails, 1120 px loses nothing.
- **Cost.**
  - Free models: $0.
  - On the paid `qwen/qwen3.8-27b`: about 2,000 input tokens per PDF page and about 1,200 per web slice (estimate, assuming 32 px per visual token), i.e. about $0.00008 per page at the cheapest provider.
  - Upload size: a synthetic text page measured 19–23 KB. Real pages with photos are probably 100–400 KB (estimate), so an 8-page embedding request is about 1–4 MB with base64 (+33%). NVIDIA's self-hosted NIM rejects images over 5 MiB by default (`NIM_SERVER_MAX_IMAGE_BYTES`, [NIM env vars](https://docs.nvidia.com/nim/nemo-retriever/embedding/2.4/environment-variables.html)). The hosted endpoint's limits are unverified, so M0 sends a full 8-page batch of heavy pages.
- **Rejected sizes.**
  - PixelRAG's 200 dpi (1654 × 2339 for A4) has about 2.3× the pixels: bigger requests, and the embedder discards the extra detail.
  - 1120 px makes footnotes and dense tables hard for the answer model to read.

### 5.5 Embedding (worker, while `pages_embedded < page_count`)

```python
def embed_pending(deps, conn, doc):
    budget = None
    if deps.cfg.embed_model.endswith(":free"):
        q = deps.openrouter.free_quota()               # one GET /api/v1/key per claimed document
        if q: budget = q["remaining"] - deps.cfg.or_reserve_requests
    deps.qc.get_collections()                          # Qdrant down -> Paused before any request is spent
    n = doc.pages_embedded
    while n < doc.page_count:
        if budget is not None and budget <= 0:
            raise RateLimited(next_utc_midnight() + 60, f"daily free quota reserve reached; {doc.page_count - n} pages pending")
        batch = list(range(n + 1, min(n + deps.cfg.embed_batch_pages, doc.page_count) + 1))
        vecs = deps.embedder.embed_pages([page_path(doc.id, p).read_bytes() for p in batch])
        store.upsert(deps.qc, doc.id, batch, vecs)     # creates the collection on first use; wait=True
        n = batch[-1]
        store.set_pages_embedded(conn, doc.id, n)      # resume point + "embedding 16/30" in the library
        if budget is not None: budget -= 1
```

- **Order:** Qdrant first, then the SQLite counter. If the app crashes between the two, the batch is re-embedded next time: one wasted request, and upserting the same ids again is harmless. If Qdrant dies mid-document, the batch in flight is lost (one request) and the worker pauses.
- **Budget:** read once per document. Questions asked while a document is embedding also use quota, so the reserve can be undershot by that many requests. The 429 handling in §8.3 covers the rest.
- **400 or 413 from `/embeddings`** → `DocError` with OpenRouter's message and the hint "if this is about size (`image_too_large` is a 400, `payload_too_large` a 413), lower EMBED_BATCH_PAGES in .env, restart, then Retry" ([error codes](https://openrouter.ai/docs/api_reference/errors-and-debugging.md)). There is no automatic batch halving; M0 tests a full batch instead.

**Request body, field mode** (`POST https://openrouter.ai/api/v1/embeddings`, header `Authorization: Bearer $OPENROUTER_API_KEY`; schema per the [embeddings API reference](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request.md)):

```json
{"model": "nvidia/nemotron-3.5-embed-8b:free",
 "input": [{"content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<B64>"}}]},
           {"content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<B64>"}}]}],
 "input_type": "passage",
 "encoding_format": "float"}
```

**Prefix mode:** no `input_type`. Each page is `{"content": [{"type": "text", "text": "passage:"}, {"type": "image_url", ...}]}`, and a question is the string `"query: <question>"`. These are the model card's prefixes (`config_sentence_transformers.json`: `{"query": "query: ", "document": "passage: "}`). The card's own code passes them as a system message (`embed("passage:", image=image)` builds `{"role": "system", "content": prefix}`), so prefix mode only approximates that.

**Response:** `data[i].embedding`, ordered by `data[i].index` when it is present (`index` is optional in the schema), otherwise in list order. The embedder checks that `len(data) == len(images)` and that all vectors have the same length; otherwise it raises `DocError("embedder returned a wrong count or length")`. Qdrant rejects a vector whose length differs from the collection's (also a `DocError`). Vectors come back L2-normalized (the model card mean-pools, then normalizes), so the app does not re-normalize.

Unverified, and settled in M0:
- Whether this provider accepts several images per request. The schema allows it.
- Whether `input_type` is forwarded, and in which spelling: NVIDIA NIM uses `query`/`passage`, the model card's vLLM client uses `query`/`document`, and OpenRouter's schema example uses `search_query`/`search_document`. The only endpoint lists `supported_parameters: []` (checked 2026-10-30), which says nothing either way. NVIDIA warns that the wrong mode causes "large drops in retrieval accuracy".

That is why `EMBED_INPUT_MODE` (`field` | `prefix`), `EMBED_QUERY_TYPE` and `EMBED_PASSAGE_TYPE` are config values.

### 5.6 Status transitions

```
 add ──► queued ──claim──► working ──► done
          ▲  ▲               │
          │  │               ├─ RateLimited ─► queued, next_attempt_at = retry_at, message = reason   ("waiting")
          │  │               ├─ Paused ──────► queued, next_attempt_at = NULL; whole worker pauses 1 → 30 min, banner
          │  │               └─ DocError or any other exception ─► error, message = text
          │  └── Retry (error, or waiting): next_attempt_at = NULL, message = NULL
          └───── make reembed: every row with page_count set → queued, pages_embedded = 0
 Delete (any status except working): row deleted, then its Qdrant points, then its folder
```

- **Claim** is atomic. `RETURNING` works: the uv Python 3.12.12 ships SQLite 3.50.4.
  ```sql
  UPDATE documents SET status = 'working', message = NULL
  WHERE id = (SELECT id FROM documents
              WHERE status = 'queued' AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
              ORDER BY id LIMIT 1)
  RETURNING id, kind, source, page_count, pages_embedded;
  ```
  `process()` then skips every step that is already complete: if `doc.pdf` or `source.jpg` exists there is no convert, if `page_count` is set there is no render, and embedding starts at `pages_embedded + 1`. **Resuming is just being claimed again.**
- **Worker loop.** Each iteration (claim plus `process`) is wrapped in `try/except`, so the thread exits only when `stop` is set. An unexpected exception logs the traceback and puts the document in `error` with `TypeName: message`. Idle: `wake.wait(5)`, so a waiting document is picked up within 5 s of its `next_attempt_at`. Paused: `wake.wait(pause)`, with `pause` starting at 60 s and doubling up to 1800 s, reset when a document finishes. Adding a document or pressing Retry wakes it early.
- **Startup recovery** (`store.recover`, after the lock is taken and before the worker starts):
  - `working` goes back to `queued`.
  - Any folder in `data/docs` whose id has no row (a crash during add or delete) gets a Qdrant delete by `doc_id`, then `rm -r`.
- **Quota waits.** While the quota is exhausted, the worker still converts and renders other documents. They only pause when they reach the embedding step.

### 5.7 Retry and delete (request thread, compare-and-set)

| Action | Allowed from | Steps |
|---|---|---|
| `retry(doc_id)` | `error`, or `queued` with a future `next_attempt_at` | `UPDATE documents SET status='queued', message=NULL, next_attempt_at=NULL WHERE id=? AND (status='error' OR (status='queued' AND next_attempt_at > :now))`, then wake the worker. A partly embedded document resumes where it stopped |
| `delete(doc_id)` | anything except `working` | `DELETE FROM documents WHERE id=? AND status != 'working'`. A `rowcount` of 1 means it is ours; 0 means "busy (being processed), try again in a moment". Then Qdrant delete by `doc_id`, then `rm -r data/docs/{id}` |

The row goes first. Once it is gone the worker can no longer claim the document, and a crash after that leaves only a folder without a row, which startup recovery removes. If Qdrant is down during a delete, the route says so and recovery finishes the job at the next start. Search drops any Qdrant hit that has no row.

There is no Re-ingest in v1. Delete, then add the same file or link again (the dedup key goes away with the row). A URL "Refresh" that keeps the old snapshot when the refetch fails is on the Later list.

### 5.8 Maintenance command (CLI)

`make reembed` (`python -m app.cli reembed`) is for an intentional `EMBED_MODEL` or input-mode change, and for recovering from Qdrant data loss. It:
1. takes `data/worker.lock`, and exits with "stop the web app first" if the app is running;
2. prints the request estimate, Σ ceil(page_count / EMBED_BATCH_PAGES), and asks for confirmation;
3. deletes the collection;
4. sets every document with `page_count` set to `queued`, `pages_embedded = 0`, `message = NULL`;
5. exits.

The next app start re-embeds from the existing JPEGs, and the first upsert creates the collection with the new metadata. `reembed` does not run the startup check it is meant to fix. The old vectors are gone, so switching back costs another re-embed.

---

## 6. Search and answer

### 6.1 Search

```python
@dataclass
class Hit:  doc_id: int; page_no: int; score: float; title: str; kind: str; source: str
            # image_url = f"/files/{doc_id}/pages/{page_no:04d}.jpg"

def search(deps, conn, q: str) -> list[list[Hit]]        # one list per document, best document first
```

1. If `q.strip()` is empty, return the message "Type a question first." No request.
2. If the collection does not exist, return "No documents yet." No request.
3. `vec = embed_query_cached(q.strip())`, a `functools.lru_cache(256)` around `embedder.embed_query`. Searching and then asking the same text costs one embedding request, not two.
   - Field mode: `{"model": EMBED_MODEL, "input": "<question>", "input_type": EMBED_QUERY_TYPE, "encoding_format": "float"}`.
   - Prefix mode: `"input": "query: <question>"`, with no `input_type`.
   - It always uses the same model as the pages, because one `Embedder` object serves both.
4. `query_points_groups(group_by="doc_id", limit=SEARCH_GROUPS=10, group_size=3)`. Then one SQLite query, `SELECT id, title, kind, source FROM documents WHERE id IN (...)`. Groups whose id has no row are dropped. Qdrant already orders the groups by their best hit.

**The UI shows, per document:**
- the title, linking to `/files/{id}/doc.pdf`, or to `/files/{id}/source.jpg` for web pages (for URLs, also a link to the source URL);
- up to 3 thumbnails (`<img width=220 loading=lazy>` using the page JPEG itself; there are no separate thumbnail files), each captioned "p. N · 0.61";
- a click on a thumbnail opens the full JPEG in a new tab.

### 6.2 Ask

```python
def build_messages(question: str, pages: list[Hit]) -> list[dict]
def ask(deps, conn, question: str) -> Answer      # Answer(text: str, sources: list[Hit], model: str) or a message
```

1. `groups = search(question)`, with the same handling for a blank question and an empty library. If there are no hits, return "No matching pages." without a chat request.
2. `sources` = the `ANSWER_PAGES` (8) best pages across all groups, by score. `group_size` is `max(ANSWER_PAGES, 3)`, so the overall top `ANSWER_PAGES` are always inside the groups: each of them is among its own document's top `ANSWER_PAGES`.
3. Images: the stored JPEGs (longest edge 1536 px) as base64 data URLs, with no `detail` field.
4. Request: `POST /api/v1/chat/completions`, non-streaming. The question text comes first, then the images, per OpenRouter's [image guide](https://openrouter.ai/docs/guides/overview/multimodal/image-understanding.md). A short label before each image ties it to its citation:

```json
{"model": "google/gemma-4-31b-it:free",
 "messages": [
  {"role": "system", "content": "<SYSTEM_PROMPT>"},
  {"role": "user", "content": [
    {"type": "text", "text": "Question: What is the invoice total?"},
    {"type": "text", "text": "[S1] invoice.pdf, page 2"},
    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<B64>"}},
    {"type": "text", "text": "[S2] notes.docx, page 1"},
    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<B64>"}},
    {"type": "text", "text": "[S3] https://en.wikipedia.org/wiki/Portable_Document_Format, page 7"},
    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<B64>"}}]}],
 "max_tokens": 2048,
 "temperature": 0.2}
```

`SYSTEM_PROMPT` is adapted from PixelRAG's `SYSTEM_PROMPT_EVIDENCE_QA` (`eval/lib/llm.py:56-59`), with its `<think>` instruction removed:

```
You answer questions using only the document pages shown as images.
Each image is preceded by a label such as [S1].
After each statement, cite the label(s) of the page(s) it comes from, e.g. "The total is 4,312 EUR [S2]."
If the pages do not contain the answer, reply "Not found in the retrieved pages." and stop.
Be concise. Answer in the language of the question.
```

Whether the Gemma endpoint accepts a `system` message is unverified, and M0 tests it. If it does not, prepend the prompt to the first user text part (a 2-line change).

5. **Response handling.** Once a provider has accepted the request, errors arrive inside an HTTP 200 ([error docs](https://openrouter.ai/docs/api_reference/errors-and-debugging.md)).
   - A top-level `error` key means failure. Show `error.message`.
   - `content = choices[0].message.content`, with any `<think>...</think>` removed (one regex; reasoning models such as the qwen upgrade may put it in `content`).
   - Empty content with `finish_reason == "length"` gets the message "The model used its whole token budget on reasoning; raise ANSWER_MAX_TOKENS in .env." Retrying does not help.
   - Show the answering model (`response.model`), and log `usage` (tokens, and cost when present).
6. **Display.** The answer text is escaped and shown pre-wrapped, with [S1]–[S3] left as plain text. Below it is a "Sources" row with 3 thumbnails, each labelled e.g. "S1 · invoice.pdf p. 2" and linking to that page's JPEG. The search results are not shown a second time.
7. **Cost per question:** one query embedding (0 if cached) plus one chat request. Interactive calls are **never retried automatically**, because each attempt costs quota. The UI shows the error and you click again.

---

## 7. Web UI

> Replaced after v1 by a React app in `web/` on a JSON API under `/api` (§15, "Web UI v2"), then redesigned as a small app with several views (§15, "Web UI v3"). The behaviour below (polling, statuses, retry/delete rules) still applies.

**Stack:** FastAPI + Jinja2 templates + htmx 2.0.11, vendored as `app/static/htmx.min.js` (52,182 bytes, from `https://unpkg.com/htmx.org@2.0.11/dist/htmx.min.js`, committed). Routes are plain `def`, so FastAPI runs them in its thread pool and blocking `httpx` calls are fine. Each request gets its own SQLite connection through a `get_conn()` dependency (WAL, `busy_timeout=5000`). Run a single process: `uvicorn app.main:app --host 127.0.0.1 --port 8000`, with no `--workers`.

| Method | Path | Does | Returns |
|---|---|---|---|
| GET | `/` | the whole page; the quota line comes from `free_quota()` (cached 60 s, left out if the call fails) | `index.html` |
| POST | `/add` | plain multipart form (not htmx): `files` (multiple) and `urls` (textarea, one per line) → `add_file` / `add_url` | 303 → `/?added=N&dupes=3,7&rejected=K` |
| GET | `/library` | document table | `_library.html` fragment |
| POST | `/docs/{id}/retry` | 5.7 | `_library.html` fragment |
| POST | `/docs/{id}/delete` | 5.7 (`hx-confirm`) | `_library.html` fragment |
| GET | `/search?q=` | 6.1 | `_results.html` fragment |
| POST | `/ask` (form `q`) | 6.2 | `_answer.html` fragment (answer + Sources) |
| GET | `/files/...` | `StaticFiles(directory=cfg.data_dir / "docs")`. Create the directory before mounting, since `StaticFiles` checks that it exists | page JPEGs, `doc.pdf`, `source.jpg`, originals |

**Search/Ask form.** htmx adds the enclosing form's values only to non-GET requests, so an `hx-get` on a button would send an empty `q` (`htmx.js` 2.0.11, lines 3675-3681). The GET therefore goes on the form itself, which also makes Enter run the cheaper Search instead of a full-page submit:

```html
<form hx-get="/search" hx-target="#results" hx-indicator="#working">
  <input name="q" required placeholder="Ask or search your documents">
  <button>Search</button>
  <button type="button" hx-post="/ask" hx-include="closest form"
          hx-target="#results" hx-indicator="#working">Ask</button>
  <span id="working" class="htmx-indicator">working…</span>
</form>
<div id="results"></div>
```

**Page layout** (one page, 4 templates: `index.html`, `_library.html`, `_results.html`, `_answer.html`):

```
PixelRAG (personal)                          Free requests today: 12/50 used (resets 01:00)
Add:  [Choose files…  .pdf .docx]   [ links, one per line ……… ]   [Add]
Ask:  [ question …………………………………………… ]   [Search] [Ask]
      #results: answer + Sources thumbnails, or results grouped by document
Library                  (banner if paused: "Worker paused: Qdrant is not running (make up); retrying 14:32")
 #  Title                     Type    Pages   Status                                       Actions
 3  https://en.wikipedia.or…  url     12/31   waiting: daily free quota; resumes 01:01     Retry  Delete
 2  report.docx               office  5/5     done                                         Delete
 1  invoice.pdf               pdf     3/3     done                                         Delete
```

- **Library polling.** The `_library.html` root carries `hx-get="/library" hx-swap="outerHTML"` and:
  - `hx-trigger="every 2s"` while some document is `working` or can be claimed now;
  - `every 30s` while only waiting documents remain;
  - no trigger once every document is `done` or `error`, so polling stops by itself.
  - The quota line is not part of the polled fragment, so polling never calls OpenRouter.
- **Rows.**
  - Action buttons are hidden while a document is `working`. Retry is shown for `error` and waiting rows.
  - A `working` row shows its stage: "converting" while `page_count` is NULL, otherwise "embedding k/n".
  - `error` shows the stored message, waiting shows the reason and the resume time, and `warning` is shown under the title.
- **Banner** above the table: "Worker paused: <reason>; retrying at HH:MM", from the worker's in-memory state. If the worker thread is no longer alive (`thread.is_alive()`), it says "Worker stopped; see the log and restart".
- **Times** are shown in local time. The server is the user's own Mac.

---

## 8. Resources and quotas

### 8.1 Local RAM (8 GB M2)

| Component | Runs in | RAM | Basis |
|---|---|---|---|
| Docker Desktop VM | macOS | 4096 MiB reserved, 1 GiB swap: the current setting, which is also the default (50% of host RAM). **No change needed** | `~/Library/Group Containers/group.com.docker/settings-store.json` |
| Gotenberg | VM, `mem_limit: 2g` | Chromium and LibreOffice start on first use and stop after 5 min idle (`*_IDLE_SHUTDOWN_TIMEOUT=5m`). About 0.5–1 GB while converting (published figures; unverified here) | Gotenberg docs, issues #950, #1023 |
| Qdrant | VM, `mem_limit: 1g` | 16 KB per page + ~20%: 5,000 pages ≈ 100 MB, 20,000 ≈ 400 MB (estimate; process overhead unverified) | Qdrant capacity planning |
| Python app | macOS | about 150–300 MB (estimate). Rendering holds one page pixmap (1187 × 1536 × 3 ≈ 5.5 MB for US Letter). Slicing a long web page briefly holds the whole decoded screenshot: about 150 MB at 40 slices, at most about 220 MB (§5.3) | — |
| Left for macOS and a browser | | about 3.5 GB | 8 − 4 − ~0.3 |

`make down` (`docker compose stop`) frees the container memory. With no containers running, Docker Desktop's Resource Saver stops the VM. The compose file sets no restart policy; `make run` starts the containers. After first use, check real usage with `docker stats --no-stream` while converting a heavy web page and a large DOCX.

### 8.2 Free-tier quota arithmetic

Limits: 20 requests/minute for every account. 50 requests/day while less than $10 of credits has ever been purchased; 1,000/day after a one-time purchase of ≥ $10. The limits apply to every model id ending in `:free` and are counted per UTC day ([limits](https://openrouter.ai/docs/api-reference/limits)). Whether rejected requests (429, 400) count is unverified; assume they do. `GET /api/v1/key` is not a model request. It is called once per claimed document and at most once a minute for the quota line, and M0 measures whether it counts.

| Action | Requests, batch of 8 | Requests, no batching |
|---|---|---|
| Ingest a 30-page PDF | **4** (8+8+8+6) | 30 |
| Ingest a 3-page DOCX | 1 | 3 |
| Ingest a web article that slices into 12 pages | 2 | 12 |
| Search | 1 | 1 |
| Ask a new question | **2** (query embedding + answer) | 2 |
| Ask right after Search with the same text | 1 (query vector cached) | 1 |
| `make reembed` of 1,000 pages (model switch or Qdrant loss) | 125 | 1,000 |
| `make smoke` (M0) | 5 (up to about 12 if another spelling or prefix mode has to be tried) | — |

What this means in practice:
- **50/day, reserve 10** (`OR_RESERVE_REQUESTS=10`, held back for questions): ingest can use 40 requests, about 320 pages/day when batched (40 unbatched), and 5 questions remain.
  - Example day: a 30-page PDF (4) + a 10-page DOCX (2) + five 10-page articles (10) = 16 requests, which leaves room for 17 questions.
  - Without batching, the 30-page PDF alone would use 30 of the 50.
- **1,000/day** (one $10 purchase, any time): with a reserve of 100, ingest gets about 900 requests, about 7,200 pages/day. The 20 RPM cap still applies: 900 requests take at least 48 minutes at the app's 3.2 s spacing.
  - The $10 is not spent by `:free` models; it stays available for paid models.
  - After buying, raise `OR_RESERVE_REQUESTS` (e.g. to 100).
- **Milestone live checks** use roughly 40 requests in total (estimate). Spread them over two days on 50/day, or buy the credits first.

### 8.3 Throttling and resuming

- **Throttle.** `OpenRouter.post()` reserves a start slot under a process-wide `threading.Lock` (`slot = max(now, last + OR_MIN_INTERVAL_S); last = slot`), releases the lock, sleeps until the slot, then sends. The default 3.2 s means ≤ 18.75 requests/min. The lock never covers network I/O, so a question asked during ingest waits at most about 3.2 s, even while an 8-image request is in flight. `GET /key` is not throttled. Only one process runs a worker (`data/worker.lock`), so there is only one throttle.
- **Quota budget.** Read once per claimed document (§5.5). When it reaches `OR_RESERVE_REQUESTS`, the document waits until the next 00:00 UTC + 60 s and its remaining pages stay pending. The budget is skipped for models without `:free`.
- **On HTTP 429.** Body: `{"error":{"code":429,"message":...,"metadata":{"error_type":"rate_limit_exceeded"}}}`. OpenRouter sends `X-RateLimit-*` headers only when it enforces the limit itself, `Retry-After` only sometimes, and the unit of `X-RateLimit-Reset` is undocumented. So the app does not depend on the headers:
  1. Call `free_quota()`. If `remaining == 0`, it is the daily lockout: `retry_at` = next 00:00 UTC + 60 s.
  2. Otherwise it is the per-minute limit or an upstream provider limit (`metadata.provider_code` present): `retry_at` = now + max(`Retry-After` or 0, 60 × 2^k), capped at 3600 s. Here k counts consecutive non-daily 429s; it is kept in memory and reset by any successful OpenRouter response.
  3. Raise `RateLimited(retry_at, reason)`. The worker sets the document back to `queued` with `next_attempt_at=retry_at` and a message such as "daily free quota reached; resumes 01:01 (22 of 30 pages pending)".

  The job never fails because of quota. When it is claimed again it continues with the pending pages.
- **Logging.** One line per OpenRouter call, e.g. `openrouter /embeddings model=… items=8 status=200 2.1s tokens=… cost=0`, so request counts and any spend are visible.

### 8.4 API errors and retries

| Source | Condition | Worker (ingest) | Interactive (search/ask) |
|---|---|---|---|
| OpenRouter | 429 | `RateLimited` (8.3) | "Rate-limited, try again in N s" or "Daily free limit reached; resets 01:00" |
| OpenRouter | 400 / 413 on `/embeddings` | `DocError` with `error.message` and the EMBED_BATCH_PAGES hint (§5.5) | show the message |
| OpenRouter | 400 on chat | — | show the message |
| OpenRouter | 401 / 402 / 404 | `Paused`, with a hint: 401 check the API key; 402 credits (paid models); 404 "no endpoints": the privacy toggle is off, or the model was withdrawn | same message and hint |
| OpenRouter | 403 (moderation) | `DocError` | show the message |
| OpenRouter | 408, 5xx, network error, `error` key inside a 200 | `Paused` (backoff 1 → 30 min) | show the message; you retry |
| OpenRouter chat | 200 with empty content, `finish_reason=length` | — | "raise ANSWER_MAX_TOKENS" |
| OpenRouter embeddings | wrong count or vector length | `DocError` | show the message |
| Gotenberg | see the §5.2 table | `DocError`, or `Paused` when it is down or full | — |
| Qdrant | connection error | `Paused("Qdrant is not running: make up")` | the same message |
| anything | unexpected exception | `DocError("TypeName: message")`, traceback logged; the loop continues | the message, with HTTP 500 |

At startup the app exits if `OPENROUTER_API_KEY` is empty or still the `sk-or-...` placeholder.

### 8.5 Upgrade path (config changes)

- **Answer model:** set `ANSWER_MODEL=qwen/qwen3.8-27b` (paid, image input). No re-embedding. On 2026-10-30 it had 21 endpoints ([endpoints](https://openrouter.ai/api/v1/models/qwen/qwen3.8-27b/endpoints)):
  - input $0.035–$0.99 per million tokens and output $1.25–$3.20 per million; the $0.039 / $1.25 figures are Chutes';
  - context 262,144 tokens on most endpoints, and 1,000,000 only on Phala, Novita and Alibaba.
  - Cost per question: 3 pages ≈ 6,000 input tokens plus about 1,500 output tokens including reasoning. That is about **$0.002** at the cheapest providers and about $0.01 at the most expensive, so $10 covers roughly 1,000–5,000 questions. To pin the cheap providers, add `"provider": {"sort": "price"}` to the chat body when switching (one line; this is cost routing, not privacy).
  - Paid requests are not subject to the 20 RPM / daily free limits.
  - Free alternatives, also a one-line change: `nvidia/nemotron-3.5-super-vl:free`, `google/gemma-4-26b-a4b-it:free`, `thinkingmachines/inkling:free`.
- **Embedding model:** set `EMBED_MODEL` (and `EMBED_INPUT_MODE` and the two `EMBED_*_TYPE` values), then run `make smoke` and `make reembed`.
  - No paid version of `nemotron-3.5-embed-8b` is listed on OpenRouter (2026-10-30).
  - Paid image-capable embedders listed: `voyageai/voyage-multimodal-3.5`, `google/gemini-embedding-2`, `amazon/titan-embed-image-v1`. Their dimensions and `input_type` handling are unverified; `make smoke` checks them before you re-embed.
- **Pacing:** after buying credits, set `OR_RESERVE_REQUESTS=100`. With paid models only, `OR_MIN_INTERVAL_S` can go down.

---

## 9. Repo layout and dependencies

```
.
├── PLAN.md
├── README.md                # setup, daily use, M0 findings, known limitations, PixelRAG credit
├── .gitignore               # .env  data/  .venv/  __pycache__/  .pytest_cache/
├── .env.example
├── .python-version          # 3.12
├── pyproject.toml
├── uv.lock
├── docker-compose.yml
├── Makefile
├── assets/icon.svg          # exists
├── app/
│   ├── __init__.py          # DocError, Paused, RateLimited
│   ├── config.py            # Config dataclass + load_config(): env → typed values with defaults
│   ├── store.py             # SQLite: connect, schema, claim, recover, CAS; Qdrant: check, upsert, groups, delete
│   ├── convert.py           # fetch_direct(), url_to_screenshot(), office_to_pdf(), render_pages(), slice_screenshot(); WEB_SHOT, SCROLL_JS
│   ├── openrouter.py        # OpenRouter: post() with slot throttle, free_quota(), chat(), 429 + error mapping
│   ├── embedder.py          # Embedder protocol, OpenRouterEmbedder (field or prefix mode)
│   ├── ingest.py            # Deps, add_file(), add_url(), process(), worker_loop(), retry(), delete(), reembed()
│   ├── main.py              # FastAPI app, lifespan, routes, search(), ask(), build_messages()
│   ├── cli.py               # smoke | reembed
│   ├── templates/           # index.html, _library.html, _results.html, _answer.html
│   └── static/htmx.min.js   # vendored 2.0.11
└── tests/
    ├── make_fixtures.py     # one-off generator; its outputs are committed
    ├── fixtures/            # sample.pdf, sample2.pdf, sample.docx, encrypted.pdf, not_a_pdf.pdf (a few KB each)
    ├── conftest.py          # tmp data dir, in-memory Qdrant, FakeEmbedder, fake httpx transports
    ├── test_render.py
    ├── test_ingest.py
    └── test_query.py
```

Estimated size: about 600 lines of Python plus about 120 lines of templates.

**Key interfaces**

```python
# embedder.py: the swap seam for a local PixelRAG embedder later
class Embedder(Protocol):
    model_id: str
    passage_mode: str                                                     # stored on the collection
    def embed_pages(self, jpegs: list[bytes]) -> list[list[float]]: ...   # documents (passage mode)
    def embed_query(self, text: str) -> list[float]: ...                  # questions (query mode)

# openrouter.py
class OpenRouter:
    def __init__(self, cfg: Config, http: httpx.Client): ...
    def post(self, path: str, payload: dict, *, timeout: float = 120) -> dict    # throttled; raises DocError/Paused/RateLimited
    def free_quota(self) -> dict | None                                          # {"used", "limit", "remaining"}
    def chat(self, model: str, messages: list[dict], *, max_tokens: int) -> tuple[str, str]   # (content, model)

# convert.py
def fetch_direct(http: httpx.Client, url: str, doc_dir: Path) -> str | None      # "pdf" | "office" | None (= screenshot)
def url_to_screenshot(http: httpx.Client, url: str) -> bytes                     # full-page JPEG, WEB_VIEWPORT_WIDTH wide
def office_to_pdf(http: httpx.Client, path: Path) -> bytes
def render_pages(pdf: Path, out_dir: Path, *, longest_edge: int, quality: int, max_pages: int) -> tuple[int, str | None]
def slice_screenshot(src: Path, out_dir: Path, *, slice_height: int, quality: int, max_pages: int) -> tuple[int, str | None]

# ingest.py: everything the worker needs, so tests can inject fakes
@dataclass
class Deps:
    cfg: Config; connect: Callable[[], sqlite3.Connection]; qc: QdrantClient
    openrouter: OpenRouter; embedder: Embedder; http: httpx.Client     # http = Gotenberg and link downloads
def add_file(conn, cfg: Config, filename: str, fileobj: BinaryIO) -> tuple[int, bool]
def add_url(conn, url: str) -> tuple[int, bool]
def process(deps: Deps, conn, doc) -> None
def worker_loop(deps: Deps, stop: threading.Event, wake: threading.Event) -> None
```

**Lifespan order** (`main.py`): check the key → take `data/worker.lock` with `fcntl.flock(LOCK_EX | LOCK_NB)` (exit "another app or reembed is running" if it is held) → `store.check_collection` → `store.recover` → start the worker as a daemon thread. On shutdown: `stop.set()`, `wake.set()`, `join(timeout=2)`.

**`pyproject.toml`.** Resolution checked with `uv pip compile` for py3.12 / aarch64-apple-darwin on 2026-10-30: 31 packages, no torch, no onnxruntime.

```toml
[project]
name = "pixelrag-app"
version = "0.1.0"
description = "Personal visual RAG: documents -> page images -> OpenRouter embeddings -> Qdrant -> vision LLM"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi==0.162.0",
  "uvicorn==0.54.0",
  "jinja2==3.1.6",
  "python-multipart==0.0.32",   # required for uploads
  "httpx==0.28.1",
  "qdrant-client==1.20.0",      # matches the server; search() is gone, use query_points*/()
  "pymupdf==1.28.2",            # newest 1.x, no dependencies; AGPL (fine for personal use). 2.0 adds onnxruntime, pymupdf4llm, pymupdf-layout
]

[dependency-groups]
dev = ["pytest==9.2.0"]

[tool.uv]
package = false

[tool.pytest.ini_options]
pythonpath = ["."]              # package = false: without this, `import app` fails at collection
```

**`.env.example`.** `config.py` reads `os.environ`, and `uv run --env-file .env` loads the file, so `python-dotenv` is not needed. Comments sit on their own lines. Only the values you are expected to change are listed; every other constant in `config.py` (`ANSWER_PAGES=8`, `ANSWER_MAX_TOKENS=2048`, `OR_MIN_INTERVAL_S=3.2`, `PAGE_LONGEST_EDGE_PX=1536`, `JPEG_QUALITY=85`, `MAX_PAGES=500` (≤ 9999), `MAX_WEB_PAGES=40`, `MAX_UPLOAD_MB=200`, `SEARCH_GROUPS=10`, `OFFICE_EXTENSIONS=.docx`, `GOTENBERG_URL=http://127.0.0.1:3100`, `QDRANT_URL=http://127.0.0.1:6333`, `QDRANT_COLLECTION=pages`, `DATA_DIR=data`) can be overridden the same way.

```
OPENROUTER_API_KEY=sk-or-...
# Models: one value each. Changing EMBED_MODEL, EMBED_INPUT_MODE or EMBED_PASSAGE_TYPE requires `make reembed`.
EMBED_MODEL=nvidia/nemotron-3.5-embed-8b:free
# field = send input_type; prefix = "query: " / "passage:" text parts. Set from the M0 smoke result.
EMBED_INPUT_MODE=field
# Field mode only. M0 may switch these to query/document or search_query/search_document.
EMBED_QUERY_TYPE=query
EMBED_PASSAGE_TYPE=passage
# Pages per embedding request; set from the M0 smoke result.
EMBED_BATCH_PAGES=8
# Web screenshot width in px. Follows the embedder's longest_edge (1120 for Nemotron 3.5 Embed); change it with the embedding model.
WEB_VIEWPORT_WIDTH=1120
# Web slice height in px. Follows the embedder's longest_edge (1120 for Nemotron 3.5 Embed); change it with the embedding model.
# Either change affects only web pages added afterwards: delete and add the old ones again.
WEB_SLICE_HEIGHT=1120
ANSWER_MODEL=google/gemma-4-31b-it:free
# Free requests per day held back for questions; raise to 100 after buying credits.
OR_RESERVE_REQUESTS=10
```

**`docker-compose.yml`.** Parsed with `docker compose config` (Compose v5.4.0) on 2026-10-30.
- Gotenberg is published on host port **3100**, because 3000 often collides with Node/Bun dev servers.
- The compose file has no `${...}` placeholders, so the OpenRouter key never reaches a container.
- Nothing is mounted into Gotenberg, and Qdrant's gRPC port 6334 is not published.

```yaml
name: pixelrag
services:
  gotenberg:
    image: gotenberg/gotenberg:8.39.0          # native arm64, ~700 MB compressed; :8 has the same digest today
    ports:
      - "127.0.0.1:3100:3000"
    environment:
      API_TIMEOUT: "300s"                      # app's httpx timeout is 330 s
      API_DISABLE_DOWNLOAD_FROM: "true"
      WEBHOOK_DISABLE: "true"
      CHROMIUM_MAX_CONCURRENCY: "1"
      CHROMIUM_IDLE_SHUTDOWN_TIMEOUT: "5m"
      LIBREOFFICE_IDLE_SHUTDOWN_TIMEOUT: "5m"
      CHROMIUM_DENY_PRIVATE_IPS: "true"        # Chromium runs --no-sandbox; keeps pages away from Qdrant, the Mac, the LAN
      LIBREOFFICE_DENY_PRIVATE_IPS: "true"
      # Default file:// rule first (setting the variable REPLACES Gotenberg's default list),
      # then common cookie-consent vendors, so their banners never load.
      CHROMIUM_DENY_LIST: '^file:(?!//\/tmp/).*,^https?://([a-z0-9-]+\.)*(cookielaw\.org|onetrust\.com|cookiebot\.com|usercentrics\.eu|privacy-center\.org|privacy-mgmt\.com|consentmanager\.net|quantcast\.com|trustarc\.com)(:|/)'
    mem_limit: 2g
    security_opt:
      - no-new-privileges:true
  qdrant:
    image: qdrant/qdrant:v1.20.0               # arm64, ~72 MB compressed
    ports:
      - "127.0.0.1:6333:6333"
    environment:
      QDRANT__TELEMETRY_DISABLED: "true"
      QDRANT__SERVICE__ENABLE_CORS: "false"    # CORS is on by default: any website could read localhost:6333
    volumes:
      - ./data/qdrant:/qdrant/storage
    mem_limit: 1g
```

**`Makefile`** (recipe lines start with a tab; `--retry-all-errors` needs curl ≥ 7.71, and macOS ships 8.7.1):

```make
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
```

---

## 10. Milestones

Each milestone is small, ends green on `make test`, and has a live check you can run by hand. The ids in the acceptance checks assume an empty library at the start of M1 (`make down && rm -rf data && make setup`); they are the ids the library shows. For checks an agent runs without a browser, `curl` equivalents are given.

### M0: Setup and live smoke checks
Tasks:
1. `.gitignore`, `.python-version`, `pyproject.toml`, `.env.example`, `docker-compose.yml`, `Makefile`. Then `make setup`.
2. **OpenRouter account.**
   - Create an API key at https://openrouter.ai/settings/keys and put it in `.env`.
   - **Required:** on https://openrouter.ai/settings/privacy, enable the toggle for **free** endpoints that may train on or log inputs. The free NVIDIA embedder endpoints are shown as `training: true` on their OpenRouter model page (the public endpoints API does not expose this field, so treat it as likely rather than confirmed), and OpenRouter's FAQ says providers that log, or whose policy it cannot confirm, are only routed to when this toggle is on. A 404 "no endpoints" from the embedder or the chat model means this toggle is off ([FAQ](https://openrouter.ai/docs/faq.md), [provider logging](https://openrouter.ai/docs/guides/privacy/provider-logging.md)). The exact toggle label is unverified.
3. Write `app/config.py`, `app/__init__.py`, `app/openrouter.py`, `app/embedder.py` and `cli smoke`. The smoke command builds pages in memory with PyMuPDF at the real render settings:
   - **A**, web-shaped (1120 × 1120 px, the size of a web slice): "The capital of Freedonia is Plumbury."
   - **B**, A4: an invoice table "Total 4,312 EUR", plus a 7 pt footnote "Ref. code K7-334-Q".
   - **C1–C6**: photo-like pages (coloured noise blocks) of about 300–500 KB each, so the batch has the full size and weight.

   It then:
   1. calls `GET /key` and prints `is_free_tier` and `free_model_daily_requests`;
   2. **request 1:** embeds all `EMBED_BATCH_PAGES` (8) pages in **one** request in the configured passage mode, and prints the count, the `index` values, the dim and the request size in MB;
   3. **request 2:** embeds page A and the question "What is the capital of Freedonia?" with no mode at all (no field, no prefix), as baseline vectors `p0` and `q0`. If mixing an image input and a text input in one request is rejected, it splits them (one more request);
   4. **request 3:** embeds "What is the capital of Freedonia?" and "What is the invoice total?" in the configured query mode;
   5. **request 4** (field mode only): embeds the first question with `input_type="bogus-mode"`. A 400, or a vector equal to `q0`, means unknown values are rejected or ignored, so any value that changes the vector is one the provider recognises;
   6. prints `cos(query, q0)` and `cos(passage A, p0)`:
      - both < 0.995: `input_type forwarded: yes`;
      - both ≥ 0.995: `forwarded: no`. Set `EMBED_INPUT_MODE=prefix` and rerun. Keep prefix mode only if its retrieval margins (step 7) are not smaller than the field-mode run's; otherwise keep `field`, which then simply has no effect;
      - only the passage cosine ≥ 0.995: rerun with `make smoke ARGS="--passage-type document"`, then with `ARGS="--query-type search_query --passage-type search_document"`;
   7. prints the retrieval check in the configured mode: question 1 must score A > B, question 2 must score B > A. It prints both margins (a rough signal from 2 pages);
   8. **request 5:** sends one chat request to `ANSWER_MODEL`: the system prompt, A labelled [S1], B labelled [S2], and "What is the capital of Freedonia, and what is the reference code in the invoice footnote?";
   9. waits 5 s, calls `GET /key` again, and prints `used` before and after, next to the number of model requests sent.

Acceptance:
- `make up` returns. `curl -s http://127.0.0.1:3100/health` shows `"status":"up"`. `curl -s http://127.0.0.1:6333/readyz` prints `all shards are ready`.
- `uv tree | grep -ciE 'torch|onnxruntime'` prints `0`.
- `make smoke` prints all of these:
  - `embed: 8 vectors, dim 4096, index [0..7], request ≈ 3 MB`, with no 400 or 413. If the 8-page request fails, rerun with `EMBED_BATCH_PAGES=4` and keep the largest size that works;
  - `input_type forwarded: yes`, or a clear `no` followed by a prefix-mode run;
  - `retrieval: q1 A > B, q2 B > A`;
  - an answer that contains "Plumbury", "K7-334-Q" and `[S1]`. If the footnote code is missed, the provider probably downscales images; note it (`PAGE_LONGEST_EDGE_PX` could then drop to 1120);
  - the `used` delta. If it is higher than the number of model requests that succeeded, `/key` calls count. That is harmless: one per document and at most one a minute for the quota line. If it is very high, drop the quota line.
- Write the findings into the README and `.env`: the input mode and spelling, the batch size, whether `/key` counts, whether a `system` message works (if not, prepend the prompt to the first user text part), and whether `<think>` shows up in `content`.
- If embedding fails with 404 "no endpoints", the privacy toggle is off. If the chat fails, try `ANSWER_MODEL=nvidia/nemotron-3.5-super-vl:free`.

### M1: PDF end-to-end through the web page
Tasks:
- `store.py`: schema, claim, recover, CAS, `check_collection`, the Qdrant calls.
- `convert.render_pages`, with `MAX_PAGES` and the tall-page warning.
- `ingest.py` for kind `pdf`: `add_file`, `process`, the embed loop with the quota budget, the `RateLimited`/`Paused`/`DocError` handling, `worker_loop` with the catch-all.
- `main.py`: the lifespan in the order given in §9, and the routes `/`, `/add`, `/library`, `/search`, `/files`.
- Templates `index.html`, `_library.html` and a minimal `_results.html`, plus the vendored htmx.
- `tests/make_fixtures.py` and the committed fixtures; `test_render.py`; the pdf parts of `test_ingest.py`.

Acceptance:
- `make test` passes. It covers render, the embed loop, resume after `RateLimited`, `Paused` leaving the document queued, an unexpected exception going to `error` while the loop continues, dedup, recovery, and the startup model-mismatch exit.
- `make run`, open http://127.0.0.1:8000, and upload `tests/fixtures/sample.pdf` (or `curl -s -o /dev/null -w '%{http_code}\n' -F files=@tests/fixtures/sample.pdf http://127.0.0.1:8000/add`, which prints `303`).
  - The log shows `doc 1: rendered 3 pages; embedded 3/3 in 1 request(s); done`.
  - `ls data/docs/1/pages` shows `0001.jpg 0002.jpg 0003.jpg`.
  - The library row goes to `done 3/3` without a reload, and then polling stops (network tab).
- Uploading `sample.pdf` again shows "already in library as #1 (done); delete it first to refresh".
- Uploading a `.txt` shows `rejected=1`. Submitting with no file and no link changes nothing.
- `curl -s localhost:6333/collections/pages` shows `points_count: 3`, vector size 4096, and the metadata `embed_model` and `passage_mode`.
- `curl -s 'http://127.0.0.1:8000/search?q=what+is+the+invoice+total'` lists `sample.pdf` first, with p. 2 first among its pages.
- **Resume, live** (3 requests): stop the app, set `EMBED_BATCH_PAGES=1`, start it, and upload `tests/fixtures/sample2.pdf` (#2). Press Ctrl-C as soon as the log shows the first batch, then `make run` again. The log shows `doc 2: 2 pages pending`, and it finishes without re-embedding page 1. Then set `EMBED_BATCH_PAGES` back.
- With the app stopped, changing `EMBED_MODEL` in `.env` and running `make run` exits with the "EMBED_MODEL changed from … run 'make reembed'" message. Revert it.

### M2: DOCX and links via Gotenberg
Tasks: `convert.fetch_direct`, `url_to_screenshot` (`WEB_SHOT` fields from §5.2, `SCROLL_JS`), `slice_screenshot` (§5.3, PyMuPDF only), `office_to_pdf`, the Gotenberg error mapping, and the convert and render steps for kinds `office` and `url`. Add the `test_ingest` cases with a fake Gotenberg that checks the exact multipart fields, and with a fake link that answers `application/pdf`; add the slicing cases to `test_render.py`.

Acceptance:
- `make test` passes. The fake Gotenberg asserts the path `/forms/chromium/screenshot/url` and the fields `width=1120`, `height=1120`, `clip=false`, `format=jpeg`, `quality=85`, `emulatedMediaType=screen`, `skipNetworkAlmostIdleEvent=false` and `waitForExpression` = `SCROLL_JS`. A link answering `application/pdf` never reaches Gotenberg.
- In **one** submit, upload `tests/fixtures/sample.docx` and paste `https://en.wikipedia.org/wiki/Portable_Document_Format` and `https://arxiv.org/pdf/1706.03762`. Three rows (#3, #4, #5) appear as `queued`, update without a reload and reach `done`; polling stops afterwards.
- #4 shows its URL as the title, and its page count. `data/docs/4/source.jpg` is 1120 px wide (check with `uv run python -c "import pymupdf; p = pymupdf.Pixmap('data/docs/4/source.jpg'); print(p.width, p.height)"`). The page count is ceil(height / 1120), one less if the last strip is under 28 px, and at most 40. Every page JPEG except the last is exactly 1120 × 1120.
- `data/docs/4/pages/0001.jpg` shows the screen layout with backgrounds. The last page shows the end of the article (references or footer) and no blank areas. Best-effort: no cookie banner.
- #5 (the arXiv link) logs `doc 5: direct PDF download`, has 15 pages, and made no Gotenberg call.
- Adding `https://nonexistent.invalid` (#6) ends in `error` with "URL blocked or host not resolvable (…)" (Gotenberg 403).
- Adding `http://host.docker.internal:6333` (#7) ends in `error` with the same message: inside Gotenberg it is a private address.
- After `docker compose stop gotenberg`, adding `https://example.com` (#8) leaves it `queued`, and the banner says "Worker paused: Gotenberg is not running (make up)". After `make up` it reaches `done` within about a minute.
- Searching "PDF/A archiving" shows #4 first.
- **Long page** (about 5 requests): add `https://en.wikipedia.org/wiki/History_of_the_United_States` (#9). It is probably taller than 40 × 1120 px (unverified), so it should reach `done` with 40 pages and the warning "page is N px tall; only the first 40 pages are kept". Open pages 0001, 0020 and 0040: each shows article text, with no blank or repeated areas. If areas are blank, or the document ends in `error` (Gotenberg 500), record it in the README; tile-by-tile capture is on the Later list.

### M3: Search and Ask UI
Tasks: the htmx form (§7), the grouped `_results.html`, `/ask`, `_answer.html`, `build_messages`, the query-embedding cache, handling of error-in-200 and empty content, the messages for 429 and a missing Qdrant, and `test_query.py`.

Acceptance:
- Typing "invoice total" and pressing Enter runs Search without reloading the page; the network tab shows `GET /search?q=invoice+total`. `sample.pdf` comes first with its p. 2 thumbnail, and clicking the thumbnail opens `/files/1/pages/0002.jpg`.
- Searching the same text twice makes one OpenRouter request (check the log).
- Ask "What is the invoice total?" shows an answer containing `4,312` and `[S1]`, plus a Sources row with 3 thumbnails labelled S1–S3 with document and page, each opening the right page image.
- Ask "Who won the 1954 World Cup?" (not in the library) shows "Not found in the retrieved pages.", or at least an answer without any [S#] citation. Record which in the README, since free models may answer from world knowledge.
- The log shows 2 requests for a new question, and 1 for an Ask right after a Search with the same text.
- Ask with an empty box shows "Type a question first" and makes 0 requests.
- With `docker compose stop qdrant`, Search shows "Qdrant is not running: make up".
- `make test` covers the message order in `build_messages`, no request for a blank question, an empty library or zero hits, error-in-200, and empty content with `finish_reason=length`.

### M4: Delete, retry, re-embed and README
Tasks: retry and delete with compare-and-set (§5.7) and their buttons; the orphan-folder sweep in `recover`; `cli reembed` with the lock, the estimate and the confirmation; the README (setup, daily use, M0 findings, quota tips, known limitations: very tall PDF pages, long web pages cut after 40 pages, logged-in sites, Qdrant loss means `make reembed`).

Acceptance:
- After Delete on #2, `curl -s -X POST localhost:6333/collections/pages/points/count -H 'content-type: application/json' -d '{"filter":{"must":[{"key":"doc_id","match":{"value":2}}]},"exact":true}'` returns `count: 0`, `data/docs/2` is gone, and the row is gone.
- Delete and Retry are hidden while a document is `working`. `make test` covers the compare-and-set refusal ("busy, try again").
- Retry on #6 takes it through `queued` → `working` → `error` again, with the same message.
- `make reembed` while the app runs says "stop the web app first". With the app stopped, it prints the estimate, and answering `n` changes nothing. Optional, about 8 requests on this library: answer `y`, then `make run`. Every document reaches `done` again, and searching "invoice total" still shows `sample.pdf` p. 2 first.
- `make test` passes.

---

## 11. Testing

**Unit tests** (`make test`; no network, no Docker; all writes under `tmp_path`):

| Test file | What it checks | How |
|---|---|---|
| `test_render.py` | 3 JPEGs named `0001..0003.jpg`, longest edge 1536; a US Letter page gives 1187 × 1536; an encrypted PDF and random bytes raise `DocError`; more than `MAX_PAGES` raises; a 200 × 2000 pt page sets the tall-page warning. `slice_screenshot`: 1120 × 2300 gives 3 slices, 1120, 1120 and 60 px tall; 1120 × 2250 gives 2 slices (the 10 px remnant is dropped); a screenshot taller than `max_pages` × 1120 keeps the first `max_pages` and sets the cut warning; a 1120 × 20 screenshot raises `DocError` | real PyMuPDF on the committed fixtures; screenshots generated with PyMuPDF in `tmp_path` (`pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 1120, 2300))`, `set_rect`, `save`) |
| `test_ingest.py` | the full pipeline for pdf, office and url; the fake Gotenberg checks the exact multipart fields, sent as form fields (no filename) except `files`, and answers the screenshot route with a 1120 × 2300 JPEG, so the url document ends with 3 pages; a link answering `application/pdf` skips Gotenberg; Gotenberg 403 → `error` with the hint, and a connect error → `Paused` with the document still queued; dedup by hash and by URL; a `RateLimited` after batch 1 leaves the document queued with `next_attempt_at` set and `pages_embedded = 8`, and a second run finishes without re-embedding (the fake counts calls); an unexpected exception → `error`, and the loop goes on; `recover()` resets `working` and removes orphan folders; delete is refused while `working`, and otherwise cleans up Qdrant, the files and the row; `check_collection` exits on a model or mode mismatch, and on a missing collection when pages were embedded | `FakeEmbedder` (deterministic vectors from a hash of the bytes), `httpx.MockTransport`, `QdrantClient(":memory:")` |
| `test_query.py` | embedder request bodies in field and prefix mode; results reordered by `index`, or kept in list order without it; a wrong count → `DocError`; throttle slots (fake clock); 429 with `remaining=0` → daily `retry_at`; 429 with `Retry-After: 7` → max(7, 60) s; repeated 429s back off; `build_messages` (question first, each label before its image, data URLs, system prompt); a blank question, a missing collection and zero hits make no request; error-in-200 and empty-content messages; `<think>` stripping | `MockTransport`, monkeypatched time, in-memory Qdrant |

**Fixtures.** Generated once with `uv run --with python-docx==1.2.0 python tests/make_fixtures.py tests/fixtures` and committed (a few KB each), so `python-docx` is not a project dependency:
- `sample.pdf`, 3 pages:
  - p1 (US Letter): "The capital of Freedonia is Plumbury.";
  - p2 (A4): an invoice table, "Total 4,312 EUR";
  - p3 (A4): a bar chart drawn with rectangles, titled "Revenue by quarter 2025".
- `sample2.pdf`, 3 pages of different text (e.g. "The Port Vell lighthouse was built in 1904."), used for the resume check.
- `sample.docx`, 2 pages: "Project Kestrel kickoff is on 12 March 2027 in Lisbon", a table, an embedded PNG, a page break, and a second section.
- `encrypted.pdf`: AES-256, user password `x`.
- `not_a_pdf.pdf`: random bytes.

There is no live test suite. `make smoke` and the milestone checks cover live behaviour, so no test can ever touch the real library.

---

## 12. Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | OpenRouter does not forward `input_type`, or expects another spelling, so pages or queries are embedded in the wrong mode and retrieval gets much worse | M0 compares each mode against a no-mode baseline, sends a bogus value to tell "recognised" from "ignored", tries three spellings, and falls back to prefix mode. The mode is config and is recorded on the collection; a change requires `make reembed` |
| 2 | The free embedder is changed or withdrawn, making every stored vector useless | Model id, dim and passage mode are on the collection and checked at startup. Page JPEGs are kept, so `make reembed` needs no re-render. Fallbacks: `nemotron-3.5-embed-1b:free`, or a paid image embedder. Later: the local PixelRAG embedder |
| 3 | The quota (50/day) makes ingest slow, or ingest uses up the requests needed for questions | Batches of 8, `OR_RESERVE_REQUESTS`, waiting and resuming, the query cache, and the one-time $10 purchase for 1,000/day |
| 4 | Unknown per-request limits (images per embedding request, request size, images per chat request) | M0 sends a full 8-page batch of heavy pages and records the working `EMBED_BATCH_PAGES`. A 400/413 ends in `error` with a hint to lower it. `ANSWER_PAGES` is a constant |
| 5 | The free answer model is overloaded, rate-limited upstream, or returns empty content after reasoning | Clear messages; switch `ANSWER_MODEL` to another free vision model or to the paid `qwen/qwen3.8-27b`; `ANSWER_MAX_TOKENS` can be overridden in `.env` |
| 6 | Web pages render badly: cookie walls, lazy images, fixed overlays, bot blocking, paywalls, intranet pages blocked by the private-IP rule | `SCROLL_JS` (lazy content), the consent-vendor deny list, `skipNetworkAlmostIdleEvent=false`. 4xx/5xx and blocked URLs end in a visible `error`. Delete and add again after a fix. Per-site cookies, user agent and allow-list are on the Later list |
| 7 | Retrieval quality without PixelRAG's tuned model; a paragraph split across two pages, or a web slice boundary cutting through a line of text (no overlap) | Search shows up to 3 pages per document, and Ask uses 3 pages. Later: neighbouring pages, hybrid text search, the local PixelRAG embedder |
| 8 | Qdrant on a VirtioFS bind mount may not fully honour fsync, so a crash during a write could corrupt the collection (a risk Qdrant maintainers have stated for 9p/VirtioFS; unverified on macOS) | Qdrant holds the only vector copy. The startup check detects a missing collection, and `make reembed` rebuilds it from the JPEGs, at a quota cost. Later / open question 6: Qdrant snapshots |
| 9 | Memory pressure on 8 GB (4 GB Docker VM plus browser) | `mem_limit` 2g/1g, Gotenberg idle shutdown, `CHROMIUM_MAX_CONCURRENCY=1`, one worker thread, page-at-a-time rendering, `make down` when not in use |
| 10 | The privacy toggle is off or reset, so free models fail with "no endpoints" | Covered in M0; the 404 hint in the banner and in error messages points to https://openrouter.ai/settings/privacy |
| 11 | A service is down, or the key or model is wrong, and every queued document would fail one after another | `Paused`: documents stay queued, one banner explains the cause, and the worker retries with backoff from 1 to 30 minutes |
| 12 | Very tall pages in uploaded PDFs become unreadable (the embedder shrinks the whole page into one 1120 px image) | A warning in the library, and a known limitation in the README. No slicer for PDF pages, by decision |
| 13 | Chromium fails, or leaves blank areas, when it captures a very tall web page in one shot. PixelRAG captures tile by tile for this reason: Chrome only rasterizes content near the viewport (`render/src/pixelrag_render/backends/cdp.py:380-383`). A JPEG also cannot be taller than 65,535 px; what Chromium does with a taller page is unverified | `MAX_WEB_PAGES=40` keeps only the first 40 slices, and `SCROLL_JS` scrolls exactly that far. The M2 long-page check looks for blank areas. A capture failure ends in a visible `error`. Later: tile-by-tile capture if long pages come out blank |

---

## 13. Later (not in v1)

- **Local PixelRAG embedder** as a second `Embedder` implementation: `Qwen/Qwen3-VL-Embedding-2B`, optionally with the LoRA `Chrisyichuan/wiki-screenshot-embedding-lora`, subfolder `lora_vit/ckpt200` (download only that subfolder, about 102 MB; the full repo is 5.95 GB).
  - Needs torch and transformers==4.57.1, plus `peft` if the LoRA is used. About 4.3 GB in bf16 on MPS; fp32 on CPU (about 8.5 GB) does not fit.
  - Copy the document/query format from `embed/src/pixelrag_embed/embed.py:453` and `serve/src/pixelrag_serve/api.py:274`, and the 875-px clamp from `embed.py:131-145`.
  - Copy the forward pass and pooling from `serve/src/pixelrag_serve/api.py:344-383`, which uses `_state["device"]` and so runs on `mps`. Do not copy `embed.py:699-744` (`_embed_direct_gpu` hardcodes `device="cuda"`), and not `embed_cpu.py`, which uses a different prompt.
  - 2048-d, so `make reembed` is required. Docker would probably have to be stopped while it runs.
  - Web pages would then need `WEB_VIEWPORT_WIDTH=875` and `WEB_SLICE_HEIGHT=1024` (its tile shape), and must be deleted and added again.
- **Qdrant snapshot backup**: mount `./data/qdrant-snapshots:/qdrant/snapshots` and add `make backup` = `curl -X POST localhost:6333/collections/pages/snapshots` (Qdrant's default snapshot path; unverified here). Restoring then needs no re-embedding.
- **Refresh for URL documents**: capture to `source.jpg.new` first, and replace the old pages only if the refetch succeeds.
- **Tile-by-tile web capture via `clip`**, if long pages come out blank (risk 13). Gotenberg's `clip=true` crops `width × height` from the top of the page and takes no y offset (`tasks.go:216-221`), so each tile would be its own request whose `waitForExpression` first shifts the page up (e.g. a CSS transform; unverified).
- **Paid image embedder** (`voyageai/voyage-multimodal-3.5`, `google/gemini-embedding-2`): a config change plus `make reembed`, after checking it with `make smoke`.
- OpenRouter's `models` fallback list for answers (a second free model when the first is overloaded). Its behaviour with `:free` models is unverified.
- Per-page text via PyMuPDF `page.get_text()` into SQLite, for snippets and keyword/hybrid search (SQLite FTS5).
- OCR for scanned PDFs.
- Adding the neighbouring page of each hit to the answer context; a per-document filter on search (`MatchAny` on `doc_id`).
- Inline citation links in the answer text; per-answer cost and `usage_daily` in the UI.
- Automatic batch halving on 400/413, if real pages ever hit a size limit.
- A CLI for add, search and ask.
- Shorter vectors (truncate to 1024/2048 and re-normalize client-side) if Qdrant RAM ever matters.
- Downscaled (1120 px) copies for embedding uploads, if request-size limits bite.
- Crawling a whole site or sitemap. Lightpanda could be used for link discovery only, never for rendering.
- Per-URL cookies, user agent and `waitDelay`; JS that removes banners; `CHROMIUM_ALLOW_LIST` for intranet hosts.
- More office formats (`.doc .odt .rtf .pptx .xlsx`: one entry in `OFFICE_EXTENSIONS` each, untested).
- Auth, a CSRF/Origin check on POST routes (any website can currently post a form to 127.0.0.1:8000), a Qdrant API key, Gotenberg basic auth, the unprivileged Qdrant image, multi-user.
- Streaming answers, chat history and follow-up questions, live per-page progress, separate thumbnail files.
- Slicing very tall uploaded pages, only if they turn out to matter.

---

## 14. Open questions for you

1. **Credits.** Buy $10 of OpenRouter credits once now (1,000 free requests/day, and money for `qwen/qwen3.8-27b` later), or start on 50/day? This sets the default `OR_RESERVE_REQUESTS` (10 vs 100) and how fast a backlog ingests.
2. **Library size.** How many documents do you expect, and how many pages does the largest have? `MAX_PAGES=500` is a guess. At 50/day, a 500-page PDF takes about 63 requests, i.e. two days.
3. **Intranet or LAN links.** Do you need them? `CHROMIUM_DENY_PRIVATE_IPS=true` blocks them; supporting them needs an explicit `CHROMIUM_ALLOW_LIST` entry per host.
4. **Logged-in or paywalled sites.** Are there any you need? Without per-site cookies (Later list), the app indexes the login or paywall page.
5. **Other office formats.** Any beyond DOCX (PPTX, XLSX, ODT, DOC)? Each is a one-line config change, but slides and spreadsheets are not tested in v1.
6. **Vector backup.** Qdrant holds the only copy of the vectors, as approved. If the collection is ever lost, rebuilding it costs a re-embed: 1,000 pages ≈ 125 requests, about 3 days on 50/day. Is that acceptable, or do you want the snapshot backup (one volume line and one Makefile target) in v1?

---

## 15. Build findings (changes to this plan)

Recorded while building; each item is the smallest fix to the plan above.

- **M0, 2026-10-30: the hosted embedder takes one image per request.** Any `/embeddings` request with two or more images returns HTTP 502 "service inference failed" from the NVIDIA provider (tried 8, 4 and 2 images, the last two only 107 KB in total); single images and text batches work. `EMBED_BATCH_PAGES` defaults to **1** (config and `.env.example`). Consequences: every page costs one request, so the quota arithmetic in §8.2 is the "no batching" column (a 30-page PDF = 30 requests; on 50/day with a reserve of 10, about 40 pages a day; `make reembed` of 1,000 pages = 1,000 requests). The 8-page batch in `make smoke` was replaced by one request per page (A, B and one heavy page). Open question 1 (buy $10 for 1,000/day) matters much more now.
- **M0: `input_type` is forwarded but ignored for images.** OpenRouter validates it (`query`, `search_query`, `passage`, `document`, `search_document`). Query mode changes text vectors; `passage`/`document` leave image vectors identical to no mode. Prefix mode is impossible for pages (text part + image in one input → 502). So `EMBED_INPUT_MODE=field`, `EMBED_QUERY_TYPE=query`, `EMBED_PASSAGE_TYPE=passage`; the spelling reruns were replaced by one 4-request probe.
- **M0: `google/gemma-4-31b-it:free` was rate-limited upstream** on every try that day. `.env` uses the plan's first alternative, `nvidia/nemotron-3.5-super-vl:free` (system message accepted, no `<think>` in `content`, reads a 7 pt footnote at 1536 px). The code default stays Gemma.
- **M0: failed requests and `GET /key` do not count** against `free_model_daily_requests`; the counter lags by about one request.
- **M1, 2026-10-30 16:10–16:30: the free 8B embedder had an image outage.** Every image request returned 502 "service inference failed" (text still worked). OpenRouter's endpoint stats showed the only provider (Nvidia) at status −5, 0% uptime over 5 min, 20% over 30 min, 74% over 1 day; the 1B fallback was at 100%. The app behaved as designed (`Paused`, document stays queued, backoff 1 → 30 min, banner). Risk: a single-provider free endpoint can be down for hours. Retested at 17:57 with the endpoint up: a single image → 200, prefix (text part + image) → 502, two images → 502, a single image again → 200. Both M0 findings stand.
- **M1: the free embedder also fails at random, and on some page shapes every time.** About half of all single-image requests return a random 502 (the same image alternates 200/502). Failed requests cost no quota, so `OpenRouter.post()` retries a 502 up to 3 more times through the throttle (`ATTEMPTS_502 = 4`, ~10 lines); only then does `Paused` apply. Separately, some shapes never succeed: US Letter (1187 × 1536, i.e. 866 × 1120 after the endpoint's resize), 852 × 1120 and 880 × 1120 failed 3/3 each, while A4 (1086 × 1536), 1152 × 1536, 998 × 1536, 773 × 1000 and every 1120 × 1120 web slice worked. Fix: `convert.square_jpeg()` centres each page on a white square **for the embedding request only** (~12 lines, PyMuPDF); the stored page JPEG and what the answer model sees are unchanged. Padded Letter, 880-wide, 16:9 slide and short last-slice pages all embedded. Retrieval with padded pages still ranks the invoice page first for "what is the invoice total" (0.36 vs 0.01 and −0.03).
- **M2, 2026-10-30: switched to paid models (user decision, $4.68 credit).** A research pass measured the paid image embedders: `voyageai/voyage-multimodal-3.5` is billed per pixel ($0.60 per billion pixels: about $0.00075 per 1120 × 1120 slice, $0.001 per A4 page), takes several images per request, accepts `input_type` query/document, returns 1024-d vectors, had 100% uptime, and reports the best ViDoRe V2 score (65.5). The answer model is paid `google/gemma-4-31b-it` (~280 tokens per image, ~$0.0001–0.0006 per question, read the 7 pt footnote). New defaults: `EMBED_MODEL=voyageai/voyage-multimodal-3.5`, `EMBED_PASSAGE_TYPE=document`, `EMBED_BATCH_PAGES=8`, `ANSWER_MODEL=google/gemma-4-31b-it`. The square padding became `EMBED_SQUARE_PAGES` (default false; it would raise Voyage's cost ~42% on A4) and is part of the stored passage mode. Measured: `make smoke` cost $0.0085 (8 heavy pages in one 4.1 MB request); re-embedding the 50-page test library took 10 requests, 30 s and $0.045. `cli reembed` was built in M2 because the switch needed it. The free-quota budget and quota line only apply when a `:free` model is configured.
- **M2: `skipNetworkAlmostIdleEvent=false` hangs Gotenberg 8.39.0.** With it, even `https://example.com` ran into the 300 s `API_TIMEOUT` (503); without it, example.com takes 0.9 s and the Wikipedia PDF article 14 s. The field is no longer sent (Gotenberg's default skips the wait); `SCROLL_JS` still waits for lazy images and fonts.
- **M2: very tall pages come back empty, not as a 500.** For `History_of_the_United_States`, Gotenberg answered HTTP 200 with 0 bytes (risk 13). Fallback in `url_to_screenshot` (~6 lines): on an empty body, capture again with `clip=true` and `height = MAX_WEB_PAGES × WEB_SLICE_HEIGHT` (44,800 px), which crops the top of the page; the document gets the warning "page too tall to capture in one shot; only the first 40 pages are kept". Side effect: during that capture the viewport is 44,800 px tall, so `100vh` sections would be stretched (Wikipedia has none). Pages 20 and 40 showed article text with images loaded, no blank areas. Tile-by-tile capture stays on the Later list.
- **M2: the title link of a PDF link document** goes to `doc.pdf` (it has no `source.jpg`); search hits carry `file_url`.
- **Web UI v2, 2026-10-30: the htmx page became a React app in `web/`** (Vite, TanStack Router and Query, shadcn/ui; user decision). The htmx routes, the Jinja2 templates, the vendored htmx and the `jinja2` dependency are gone. FastAPI now has JSON routes that call the same functions: `GET /api/library` (documents with a `waiting` flag, the banner, and `poll_ms` = 2000 / 30000 / null, so the polling rule stays on the server), `GET /api/quota`, `POST /api/add` (multipart; returns `added`, `duplicates` and the `rejected` messages), `GET /api/search?q=`, `POST /api/ask` (JSON `{"q": ...}`), `POST /api/docs/{id}/retry` and `DELETE /api/docs/{id}`. User-facing errors stay 200 responses with a `message`. The lifespan mounts `web/dist` at `/` after `/files`, since a mount at `/` catches every path after it. `make run` rebuilds `web/dist` when its sources change; for development, Vite proxies `/api` and `/files` to port 8000.
- **Web UI v3, 2026-10-30: from one long page to an app with views** (user verdict on v2: "horrible UX").
  - **Routes:** `/` is Ask (Enter asks; an Ask | Search switch searches only), with the question in the URL
    (`?q=…&mode=search`). `/library` lists the documents and `/docs/{id}` shows one with all its pages
    (`?page=N` opens the viewer).
  - **Add** is a dialog from the top bar; files dropped anywhere open it, and an empty library shows the same
    panel as its home page.
  - **Page viewer:** citations [S1]–[S3] in the answer and every thumbnail open the page large in a dialog,
    with ←/→ through its document.
  - **Answers** are rendered as Markdown (`react-markdown`, the one new dependency; raw HTML off). The
    citations are rewritten to `#cite-N` links and drawn as buttons.
  - **Library query in the top bar:** it lives in the app shell, so polling and the "Processing N / N
    failed" hint stay live on every page.
  - Answers and searches are cached for the session. Reloading a `/?q=` page asks again (user decision).
  - Dark mode follows the system, with a toggle (stored in `localStorage`).
  - **API changes:**
    - Each library document has `file_url` (`doc.pdf` or `source.jpg`, `null` until it exists). A link to a PDF
      is `kind: url` with a `doc.pdf`, so the client cannot derive it.
    - `/api/ask` also returns the search `groups` it already computed.
    - FastAPI serves `index.html` for client routes such as `/library` on reload (`SPAFiles`: a 404 for a path
      without a file extension and outside `api/`).
- **Web UI v4, 2026-11-01: a look of its own, a settings panel and a library filter** (user request).
  - **Look:** a near-monochrome paper-and-graphite UI, so the colour comes from the document pages, with one
    muted sage accent (#6b8a78; the user rejected a blue and then a highlighter-yellow accent as too bright) for
    what was found or is pointed at: cited and hovered pages, link underlines, the focused ask box. Dark mode is
    neutral graphite with a mid-tone sage (#7f9a88; a pastel sage looked mint there), and page rings sit 2 px off
    the page so they show against white pages in both themes. Plus Jakarta Sans (as on openrouter.ai; user choice) replaces Geist, with Onest as the
    fallback for Cyrillic, which Plus Jakarta Sans lacks.
  - **Home page:** a larger single-field ask box, and below it the newest documents' first pages in their own
    colours (a cyanotype tint was tried and rejected by the user). The Library tab shows no document count.
  - **`GET /api/config`:** the answer and embedding settings, page image sizes and limits, read-only from
    `.env` (never the API key), shown in a popover in the top bar.
  - **Library filter:** client-side, every word must appear in the title or link. No server search: pages are
    images without text, and the semantic Search on the home page already covers finding pages by content.
- **Renamed to GriRAG, 2026-11-01 (user decision)**, with a new mark: a page outline that reads as a G, its dog-ear
  in the sage accent (`web/src/components/logo.tsx`, `web/public/favicon.svg`, `assets/icon.svg`). Only
  user-facing names changed (UI, tab titles, README title, the Python package name in `pyproject.toml`). The repo
  folder, the Compose project name `pixelrag` and the Qdrant collection stay, since renaming the Compose project
  would start new containers next to the running ones. References to the upstream PixelRAG project are credits
  and stay as they are.

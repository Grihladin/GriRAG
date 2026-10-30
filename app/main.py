"""FastAPI app, lifespan, routes, search(), ask(), build_messages(). PLAN.md §6-7."""
import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from qdrant_client import QdrantClient
from starlette.concurrency import run_in_threadpool

from app import DocError, Paused, RateLimited, ingest, store
from app.config import check_key, load_config
from app.embedder import OpenRouterEmbedder, image_part
from app.openrouter import OpenRouter, next_utc_midnight

log = logging.getLogger("app.main")
HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")

SYSTEM_PROMPT = """You answer questions using only the document pages shown as images.
Each image is preceded by a label such as [S1].
After each statement, cite the label(s) of the page(s) it comes from, e.g. "The total is 4,312 EUR [S2]."
If the pages do not contain the answer, reply "Not found in the retrieved pages." and stop.
Be concise. Answer in the language of the question."""


# ---------------------------------------------------------------- search and answer

@dataclass
class Hit:
    doc_id: int
    page_no: int
    score: float
    title: str
    kind: str
    source: str
    file_url: str = ""               # the whole document: doc.pdf, or source.jpg for screenshotted web pages

    @property
    def image_url(self) -> str:
        return f"/files/{self.doc_id}/pages/{self.page_no:04d}.jpg"


def search(deps: ingest.Deps, conn, q: str) -> list[list[Hit]] | str:
    """One list of hits per document, best document first; or a message for the user."""
    q = q.strip()
    if not q:
        return "Type a question first."
    try:
        if not store.collection_exists(deps.qc, deps.cfg):
            return "No documents yet."
        vec = deps.embed_query(q)
        groups = store.search_groups(deps.qc, deps.cfg, vec)
    except RateLimited as e:
        return user_message(e)
    except (DocError, Paused) as e:
        return str(e)
    ids = [g.id for g in groups]
    rows = {r["id"]: r for r in conn.execute(
        f"SELECT id, title, kind, source FROM documents WHERE id IN ({','.join('?' * len(ids))})", ids)}
    def file_url(doc_id: int) -> str:
        pdf = (store.doc_dir(deps.cfg, doc_id) / "doc.pdf").exists()
        return f"/files/{doc_id}/{'doc.pdf' if pdf else 'source.jpg'}"

    return [[Hit(g.id, h.payload["page"], h.score, rows[g.id]["title"], rows[g.id]["kind"], rows[g.id]["source"],
                 file_url(g.id)) for h in g.hits] for g in groups if g.id in rows]


def user_message(e: RateLimited) -> str:
    if "daily" in e.reason:
        return f"Daily free limit reached; resets {datetime.fromtimestamp(next_utc_midnight()).strftime('%H:%M')}"
    return f"Rate-limited, try again in {max(int(e.retry_at - time.time()), 1)} s"


@dataclass
class Answer:
    text: str
    sources: list[Hit]
    model: str


def ask(deps: ingest.Deps, conn, question: str) -> Answer | str:
    """Answer from the ANSWER_PAGES best pages overall; or a message for the user. Never retried automatically."""
    groups = search(deps, conn, question)
    if isinstance(groups, str):
        return groups
    if not groups:
        return "No matching pages."
    sources = sorted((h for g in groups for h in g), key=lambda h: h.score, reverse=True)[:deps.cfg.answer_pages]
    pages = [(f"[S{i}] {h.title}, page {h.page_no}", store.page_path(deps.cfg, h.doc_id, h.page_no).read_bytes())
             for i, h in enumerate(sources, start=1)]
    try:
        content, model = deps.openrouter.chat(deps.cfg.answer_model, build_messages(question.strip(), pages),
                                              max_tokens=deps.cfg.answer_max_tokens)
    except RateLimited as e:
        return user_message(e)
    except (DocError, Paused) as e:
        return str(e)
    return Answer(re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip(), sources, model)


def build_messages(question: str, pages: list[tuple[str, bytes]]) -> list[dict]:
    """pages: (label, jpeg) in citation order, e.g. ("[S1] invoice.pdf, page 2", b"...")."""
    content = [{"type": "text", "text": f"Question: {question}"}]
    for label, jpeg in pages:
        content += [{"type": "text", "text": label}, image_part(jpeg)]
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]


# ---------------------------------------------------------------- app and lifespan

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = load_config()
    check_key(cfg)
    for sub in ("docs", "tmp"):
        (cfg.data_dir / sub).mkdir(parents=True, exist_ok=True)
    lock = ingest.take_lock(cfg)
    if lock is None:
        raise SystemExit("another app or reembed is running")
    http = httpx.Client(timeout=330)
    orr = OpenRouter(cfg, http)
    qc = QdrantClient(url=cfg.qdrant_url, timeout=30)
    conn = store.connect(cfg)
    try:
        store.check_collection(qc, conn, cfg)
        store.recover(conn, qc, cfg)
    except Paused as e:
        raise SystemExit(str(e))
    finally:
        conn.close()
    deps = ingest.Deps(cfg=cfg, connect=lambda: store.connect(cfg), qc=qc, openrouter=orr,
                       embedder=OpenRouterEmbedder(cfg, orr), http=http)
    stop = threading.Event()
    worker = threading.Thread(target=ingest.worker_loop, args=(deps, stop), daemon=True, name="worker")
    worker.start()
    app.state.deps, app.state.worker = deps, worker
    app.mount("/files", StaticFiles(directory=cfg.data_dir / "docs"), name="files")
    try:
        yield
    finally:
        stop.set()
        deps.wake.set()
        worker.join(timeout=2)
        lock.close()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


def get_deps(request: Request) -> ingest.Deps:
    return request.app.state.deps


def get_conn(deps: ingest.Deps = Depends(get_deps)):
    conn = deps.connect()
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------- library view

def library_context(request: Request, conn) -> dict:
    now = time.time()
    rows = store.list_docs(conn)
    claimable = any(r["status"] == "working" or (r["status"] == "queued" and (r["next_attempt_at"] or 0) <= now)
                    for r in rows)
    waiting = any(r["status"] == "queued" for r in rows)
    deps, worker = request.app.state.deps, request.app.state.worker
    banner = None
    if not worker.is_alive():
        banner = "Worker stopped; see the log and restart"
    elif deps.status.paused:
        banner = f"Worker paused: {deps.status.paused}; retrying {fmt_time(deps.status.until)}"
    return {"request": request, "docs": rows, "now": now, "banner": banner,
            "poll": "every 2s" if claimable else "every 30s" if waiting else None}


def fmt_time(ts) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M") if ts else ""


templates.env.filters["hhmm"] = fmt_time


def quota_line(deps: ingest.Deps) -> str | None:
    if not any(m.endswith(":free") for m in (deps.cfg.embed_model, deps.cfg.answer_model)):
        return None
    q = deps.openrouter.free_quota()
    if not q:
        return None
    return f"Free requests today: {q['used']}/{q['limit']} used (resets {fmt_time(next_utc_midnight())})"


# ---------------------------------------------------------------- routes

@app.get("/", response_class=HTMLResponse)
def index(request: Request, added: int = 0, dupes: str = "", rejected: int = 0,
          deps: ingest.Deps = Depends(get_deps), conn=Depends(get_conn)):
    dupe_rows = [r for i in dupes.split(",") if i.isdigit() and (r := store.get(conn, int(i)))]
    return templates.TemplateResponse(request, "index.html", {
        **library_context(request, conn), "quota": quota_line(deps),
        "added": added, "dupes": dupe_rows, "rejected": rejected})


@app.post("/add")
async def add(request: Request, deps: ingest.Deps = Depends(get_deps)):
    form = await request.form()
    files = [f for f in form.getlist("files") if getattr(f, "filename", None)]
    urls = [u for u in str(form.get("urls") or "").splitlines() if u.strip()]

    def work():
        added, dupes, rejected = 0, [], 0
        conn = deps.connect()
        try:
            for f in files:
                try:
                    doc_id, created = ingest.add_file(conn, deps.cfg, f.filename, f.file)
                except ingest.Rejected as e:
                    log.info("rejected: %s", e)
                    rejected += 1
                    continue
                added, dupes = (added + 1, dupes) if created else (added, dupes + [doc_id])
            for u in urls:
                try:
                    doc_id, created = ingest.add_url(conn, u)
                except ingest.Rejected as e:
                    log.info("rejected: %s", e)
                    rejected += 1
                    continue
                added, dupes = (added + 1, dupes) if created else (added, dupes + [doc_id])
        finally:
            conn.close()
        return added, dupes, rejected

    added, dupes, rejected = await run_in_threadpool(work)
    await form.close()
    if added:
        deps.wake.set()
    return RedirectResponse(f"/?added={added}&dupes={','.join(map(str, dupes))}&rejected={rejected}",
                            status_code=303)


@app.get("/library", response_class=HTMLResponse)
def library(request: Request, conn=Depends(get_conn)):
    return templates.TemplateResponse(request, "_library.html", library_context(request, conn))


@app.get("/search", response_class=HTMLResponse)
def search_route(request: Request, q: str = "", deps: ingest.Deps = Depends(get_deps), conn=Depends(get_conn)):
    result = search(deps, conn, q)
    return templates.TemplateResponse(request, "_results.html", {
        "groups": result if isinstance(result, list) else [],
        "message": result if isinstance(result, str) else (None if result else "No matching pages.")})


@app.post("/ask", response_class=HTMLResponse)
def ask_route(request: Request, q: str = Form(""), deps: ingest.Deps = Depends(get_deps), conn=Depends(get_conn)):
    result = ask(deps, conn, q)
    return templates.TemplateResponse(request, "_answer.html", {
        "answer": result if isinstance(result, Answer) else None,
        "message": result if isinstance(result, str) else None})


@app.post("/docs/{doc_id}/retry", response_class=HTMLResponse)
def retry_route(request: Request, doc_id: int, deps: ingest.Deps = Depends(get_deps), conn=Depends(get_conn)):
    return library_with_notice(request, conn, ingest.retry(deps, conn, doc_id))


@app.post("/docs/{doc_id}/delete", response_class=HTMLResponse)
def delete_route(request: Request, doc_id: int, deps: ingest.Deps = Depends(get_deps), conn=Depends(get_conn)):
    return library_with_notice(request, conn, ingest.delete(deps, conn, doc_id))


def library_with_notice(request: Request, conn, notice: str | None):
    ctx = library_context(request, conn)
    if notice:
        ctx["banner"] = f"#{request.path_params['doc_id']}: {notice}"
    return templates.TemplateResponse(request, "_library.html", ctx)

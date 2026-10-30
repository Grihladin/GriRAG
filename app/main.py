"""FastAPI app, lifespan, routes, search(), ask(), build_messages(). PLAN.md §6-7."""
import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import Body, Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from qdrant_client import QdrantClient
from starlette.concurrency import run_in_threadpool

from app import DocError, Paused, RateLimited, ingest, store
from app.config import check_key, load_config
from app.embedder import OpenRouterEmbedder, image_part
from app.openrouter import OpenRouter, next_utc_midnight

log = logging.getLogger("app.main")
HERE = Path(__file__).parent
WEB_DIST = HERE.parent / "web" / "dist"

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
    return [[Hit(g.id, h.payload["page"], h.score, rows[g.id]["title"], rows[g.id]["kind"], rows[g.id]["source"],
                 file_url(deps.cfg, g.id) or "") for h in g.hits] for g in groups if g.id in rows]


def file_url(cfg, doc_id: int) -> str | None:
    """The whole document: doc.pdf (PDF, DOCX, PDF links), or source.jpg (screenshotted web pages); None until it exists."""
    for name in ("doc.pdf", "source.jpg"):
        if (store.doc_dir(cfg, doc_id) / name).exists():
            return f"/files/{doc_id}/{name}"
    return None


def user_message(e: RateLimited) -> str:
    if "daily" in e.reason:
        return f"Daily free limit reached; resets {datetime.fromtimestamp(next_utc_midnight()).strftime('%H:%M')}"
    return f"Rate-limited, try again in {max(int(e.retry_at - time.time()), 1)} s"


@dataclass
class Answer:
    text: str
    sources: list[Hit]
    model: str
    groups: list[list[Hit]]          # every matching page, as search() returns them


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
    return Answer(re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip(), sources, model, groups)


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
    if (WEB_DIST / "index.html").exists():      # last: a mount at "/" catches everything after it
        app.mount("/", SPAFiles(directory=WEB_DIST, html=True), name="web")
    else:
        log.warning("web/dist not built; run make web (or use the Vite dev server)")
    try:
        yield
    finally:
        stop.set()
        deps.wake.set()
        worker.join(timeout=2)
        lock.close()


class SPAFiles(StaticFiles):
    """web/dist. Other paths without a file extension get index.html, so client routes like /library survive a reload."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code != 404 or path.split("/")[0] == "api" or "." in path.rsplit("/", 1)[-1]:
                raise
            return await super().get_response("index.html", scope)


app = FastAPI(lifespan=lifespan)


def get_deps(request: Request) -> ingest.Deps:
    return request.app.state.deps


def get_conn(deps: ingest.Deps = Depends(get_deps)):
    conn = deps.connect()
    try:
        yield conn
    finally:
        conn.close()


def fmt_time(ts) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M") if ts else ""


# ---------------------------------------------------------------- JSON API for web/ (PLAN.md §7)

@app.get("/api/library")
def library(request: Request, conn=Depends(get_conn)):
    """Documents, the worker banner, and how often the UI should poll (null: stop)."""
    now = time.time()
    deps, worker = request.app.state.deps, request.app.state.worker
    docs = [{**dict(r), "waiting": r["status"] == "queued" and (r["next_attempt_at"] or 0) > now,
             "file_url": file_url(deps.cfg, r["id"])} for r in store.list_docs(conn)]
    banner = None
    if not worker.is_alive():
        banner = "Worker stopped; see the log and restart"
    elif deps.status.paused:
        banner = f"Worker paused: {deps.status.paused}; retrying {fmt_time(deps.status.until)}"
    claimable = any(d["status"] == "working" or (d["status"] == "queued" and not d["waiting"]) for d in docs)
    waiting = any(d["status"] == "queued" for d in docs)
    return {"docs": docs, "banner": banner, "poll_ms": 2000 if claimable else 30000 if waiting else None}


@app.get("/api/quota")
def quota(deps: ingest.Deps = Depends(get_deps)):
    """Free-request line, only when a :free model is configured. Separate so polling never calls OpenRouter."""
    if not any(m.endswith(":free") for m in (deps.cfg.embed_model, deps.cfg.answer_model)):
        return {"quota": None}
    q = deps.openrouter.free_quota()
    return {"quota": q and f"Free requests today: {q['used']}/{q['limit']} used "
                           f"(resets {fmt_time(next_utc_midnight())})"}


@app.post("/api/add")
async def add(request: Request, deps: ingest.Deps = Depends(get_deps)):
    """Multipart: files (multiple) and urls (one per line)."""
    form = await request.form()
    files = [f for f in form.getlist("files") if getattr(f, "filename", None)]
    urls = [u for u in str(form.get("urls") or "").splitlines() if u.strip()]

    def work():
        result = {"added": 0, "duplicates": [], "rejected": []}
        conn = deps.connect()

        def record(add):
            try:
                doc_id, created = add()
            except ingest.Rejected as e:
                log.info("rejected: %s", e)
                result["rejected"].append(str(e))
                return
            if created:
                result["added"] += 1
            else:
                r = store.get(conn, doc_id)
                result["duplicates"].append({"id": doc_id, "title": r["title"], "status": r["status"]})

        try:
            for f in files:
                record(lambda: ingest.add_file(conn, deps.cfg, f.filename, f.file))
            for u in urls:
                record(lambda: ingest.add_url(conn, u))
        finally:
            conn.close()
        return result

    result = await run_in_threadpool(work)
    await form.close()
    if result["added"]:
        deps.wake.set()
    return result


def hit_json(h: Hit) -> dict:
    return {**asdict(h), "image_url": h.image_url}


@app.get("/api/search")
def search_route(q: str = "", deps: ingest.Deps = Depends(get_deps), conn=Depends(get_conn)):
    result = search(deps, conn, q)
    if isinstance(result, str):
        return {"groups": [], "message": result}
    return {"groups": [[hit_json(h) for h in g] for g in result], "message": None if result else "No matching pages."}


@app.post("/api/ask")
def ask_route(q: str = Body("", embed=True), deps: ingest.Deps = Depends(get_deps), conn=Depends(get_conn)):
    result = ask(deps, conn, q)
    if isinstance(result, str):
        return {"answer": None, "groups": [], "message": result}
    return {"answer": {"text": result.text, "model": result.model, "sources": [hit_json(h) for h in result.sources]},
            "groups": [[hit_json(h) for h in g] for g in result.groups], "message": None}


@app.post("/api/docs/{doc_id}/retry")
def retry_route(doc_id: int, deps: ingest.Deps = Depends(get_deps), conn=Depends(get_conn)):
    return {"message": ingest.retry(deps, conn, doc_id)}


@app.delete("/api/docs/{doc_id}")
def delete_route(doc_id: int, deps: ingest.Deps = Depends(get_deps), conn=Depends(get_conn)):
    return {"message": ingest.delete(deps, conn, doc_id)}

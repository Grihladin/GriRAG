"""The JSON API under /api that the UI talks to. User-facing errors are 200 responses with a `message`. PLAN.md §7."""
import time
from datetime import datetime

from fastapi import APIRouter, Body, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.backend import documents, store
from app.backend.deps import Deps
from app.backend.rag.answer import ask
from app.backend.rag.openrouter import next_utc_midnight
from app.backend.rag.search import Hit, search

router = APIRouter(prefix="/api")


def get_deps(request: Request) -> Deps:
    return request.app.state.deps


def get_conn(deps: Deps = Depends(get_deps)):
    """One SQLite connection per request."""
    conn = deps.connect()
    try:
        yield conn
    finally:
        conn.close()


def fmt_time(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M") if ts else ""


def groups_json(groups: list[list[Hit]]) -> list[list[dict]]:
    return [[h.to_json() for h in g] for g in groups]


@router.get("/library")
def library(request: Request, conn=Depends(get_conn)):
    """Documents, the worker banner, and how often the UI should poll (null: stop)."""
    now = time.time()
    deps, worker = request.app.state.deps, request.app.state.worker
    docs = [{**dict(r), "waiting": r["status"] == "queued" and (r["next_attempt_at"] or 0) > now,
             "file_url": store.file_url(deps.cfg, r["id"])} for r in store.list_docs(conn)]
    banner = None
    if not worker.is_alive():
        banner = "Worker stopped; see the log and restart"
    elif deps.status.paused:
        banner = f"Worker paused: {deps.status.paused}; retrying {fmt_time(deps.status.until)}"
    claimable = any(d["status"] == "working" or (d["status"] == "queued" and not d["waiting"]) for d in docs)
    waiting = any(d["status"] == "queued" for d in docs)
    return {"docs": docs, "banner": banner, "poll_ms": 2000 if claimable else 30000 if waiting else None}


@router.get("/quota")
def quota(deps: Deps = Depends(get_deps)):
    """Free-request line, only when a :free model is configured. Separate so polling never calls OpenRouter."""
    if not any(m.endswith(":free") for m in (deps.cfg.embed_model, deps.cfg.answer_model)):
        return {"quota": None}
    q = deps.openrouter.free_quota()
    return {"quota": q and f"Free requests today: {q['used']}/{q['limit']} used "
                           f"(resets {fmt_time(next_utc_midnight())})"}


@router.get("/config")
def config(deps: Deps = Depends(get_deps)):
    """The settings that shape answers and search, read-only (they come from .env). Never the API key."""
    c = deps.cfg
    return {
        "answer": {"model": c.answer_model, "temperature": c.answer_temperature,
                   "reasoning_effort": c.answer_reasoning_effort or None, "pages": c.answer_pages,
                   "max_tokens": c.answer_max_tokens},
        "embedding": {"model": c.embed_model, "batch_pages": c.embed_batch_pages,
                      "query_type": c.embed_query_type, "passage_mode": c.passage_mode},
        "pages": {"longest_edge_px": c.page_longest_edge_px, "jpeg_quality": c.jpeg_quality,
                  "web_viewport_width": c.web_viewport_width, "web_slice_height": c.web_slice_height},
        "limits": {"max_pages": c.max_pages, "max_web_pages": c.max_web_pages, "max_upload_mb": c.max_upload_mb},
    }


@router.post("/add")
async def add(request: Request, deps: Deps = Depends(get_deps)):
    """Multipart: files (multiple) and urls (one per line)."""
    form = await request.form()
    files = [(f.filename, f.file) for f in form.getlist("files") if getattr(f, "filename", None)]
    urls = [u for u in str(form.get("urls") or "").splitlines() if u.strip()]

    def work():
        conn = deps.connect()
        try:
            return documents.add_all(conn, deps.cfg, files, urls)
        finally:
            conn.close()

    result = await run_in_threadpool(work)
    await form.close()
    if result["added"]:
        deps.wake.set()
    return result


@router.get("/search")
def search_route(q: str = "", deps: Deps = Depends(get_deps), conn=Depends(get_conn)):
    result = search(deps, conn, q)
    if isinstance(result, str):
        return {"groups": [], "message": result}
    return {"groups": groups_json(result), "message": None if result else "No matching pages."}


@router.post("/ask")
def ask_route(q: str = Body("", embed=True), deps: Deps = Depends(get_deps), conn=Depends(get_conn)):
    result = ask(deps, conn, q)
    if isinstance(result, str):
        return {"answer": None, "groups": [], "message": result}
    return {"answer": {"text": result.text, "model": result.model, "sources": [h.to_json() for h in result.sources]},
            "groups": groups_json(result.groups), "message": None}


@router.post("/docs/{doc_id}/retry")
def retry(doc_id: int, deps: Deps = Depends(get_deps), conn=Depends(get_conn)):
    return {"message": documents.retry(deps, conn, doc_id)}


@router.delete("/docs/{doc_id}")
def delete(doc_id: int, deps: Deps = Depends(get_deps), conn=Depends(get_conn)):
    return {"message": documents.delete(deps, conn, doc_id)}

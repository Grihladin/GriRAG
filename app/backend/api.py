"""The JSON API under /api that the UI talks to. User-facing errors are 200 responses with a `message`. PLAN.md §7."""
import sqlite3
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Form, Request, UploadFile

from app.backend import documents, store
from app.backend.deps import Deps
from app.backend.rag.answer import ask
from app.backend.rag.openrouter import next_utc_midnight
from app.backend.rag.search import Hit, search

router = APIRouter(prefix="/api")


def get_deps(request: Request) -> Deps:
    return request.app.state.deps


DepsDep = Annotated[Deps, Depends(get_deps)]


def get_conn(deps: DepsDep) -> Iterator[sqlite3.Connection]:
    """One SQLite connection per request."""
    conn = deps.connect()
    try:
        yield conn
    finally:
        conn.close()


ConnDep = Annotated[sqlite3.Connection, Depends(get_conn)]


def fmt_time(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M") if ts else ""


def groups_json(groups: list[list[Hit]]) -> list[list[dict]]:
    return [[h.to_json() for h in g] for g in groups]


@router.get("/library")
def library(request: Request, deps: DepsDep, conn: ConnDep):
    """Documents, the worker banner, and how often the UI should poll (null: stop)."""
    now = time.time()
    worker = request.app.state.worker
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
def quota(deps: DepsDep):
    """Free-request line, only when a :free model is configured. Separate so polling never calls OpenRouter."""
    if not any(m.endswith(":free") for m in (deps.cfg.embed_model, deps.cfg.answer_model)):
        return {"quota": None}
    q = deps.openrouter.free_quota()
    return {"quota": q and f"Free requests today: {q['used']}/{q['limit']} used "
                           f"(resets {fmt_time(next_utc_midnight())})"}


@router.get("/config")
def config(deps: DepsDep):
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
def add(deps: DepsDep, conn: ConnDep, files: Annotated[list[UploadFile] | None, File()] = None,
        urls: Annotated[str, Form()] = ""):
    """Multipart: files (multiple) and urls (one per line)."""
    result = documents.add_all(conn, deps.cfg, [(f.filename, f.file) for f in files or []],
                               [u for u in urls.splitlines() if u.strip()])
    if result["added"]:
        deps.wake.set()
    return result


@router.get("/search")
def search_route(deps: DepsDep, conn: ConnDep, q: str = ""):
    result = search(deps, conn, q)
    if isinstance(result, str):
        return {"groups": [], "message": result}
    return {"groups": groups_json(result), "message": None if result else "No matching pages."}


@router.post("/ask")
def ask_route(deps: DepsDep, conn: ConnDep, q: Annotated[str, Body(embed=True)] = ""):
    result = ask(deps, conn, q)
    if isinstance(result, str):
        return {"answer": None, "groups": [], "message": result}
    return {"answer": {"text": result.text, "model": result.model, "sources": [h.to_json() for h in result.sources]},
            "groups": groups_json(result.groups), "message": None}


@router.post("/docs/{doc_id}/retry")
def retry(doc_id: int, deps: DepsDep, conn: ConnDep):
    return {"message": documents.retry(deps, conn, doc_id)}


@router.delete("/docs/{doc_id}")
def delete(doc_id: int, deps: DepsDep, conn: ConnDep):
    return {"message": documents.delete(deps, conn, doc_id)}

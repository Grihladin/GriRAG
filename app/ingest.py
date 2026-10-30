"""Adding documents, the worker (convert -> render -> embed -> upsert), retry, delete, reembed. PLAN.md §5."""
import fcntl
import hashlib
import logging
import os
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx
from qdrant_client import QdrantClient

from app import DocError, Paused, RateLimited, convert, store
from app.config import Config
from app.embedder import Embedder
from app.openrouter import OpenRouter, next_utc_midnight

log = logging.getLogger("app.ingest")


@dataclass
class WorkerStatus:
    paused: str | None = None        # banner text while the worker pauses
    until: float | None = None


@dataclass
class Deps:
    cfg: Config
    connect: Callable[[], sqlite3.Connection]
    qc: QdrantClient
    openrouter: OpenRouter
    embedder: Embedder
    http: httpx.Client                                # Gotenberg and link downloads
    wake: threading.Event = field(default_factory=threading.Event)
    status: WorkerStatus = field(default_factory=WorkerStatus)
    embed_query: Callable[[str], list[float]] = None  # cached embedder.embed_query

    def __post_init__(self):
        if self.embed_query is None:
            self.embed_query = lru_cache(256)(self.embedder.embed_query)


# ---------------------------------------------------------------- adding (request thread)

class Rejected(ValueError):
    pass


def _insert(conn, cfg: Config, kind: str, source: str, key: str, tmp: Path | None, name: str | None
            ) -> tuple[int, bool]:
    if row := store.by_dedup(conn, key):
        if tmp:
            tmp.unlink(missing_ok=True)
        return row["id"], False
    d = None
    try:
        cur = conn.execute("INSERT INTO documents (kind, source, title, dedup_key) VALUES (?, ?, ?, ?)",
                           (kind, source, source, key))
        doc_id = cur.lastrowid
        if tmp:
            d = store.doc_dir(cfg, doc_id)
            d.mkdir(parents=True)
            os.replace(tmp, d / name)
        conn.commit()
        return doc_id, True
    except sqlite3.IntegrityError:                    # a concurrent duplicate won the race
        conn.rollback()
        if tmp:
            tmp.unlink(missing_ok=True)
        return store.by_dedup(conn, key)["id"], False
    except BaseException:
        conn.rollback()
        if d:
            shutil.rmtree(d, ignore_errors=True)
        if tmp:
            tmp.unlink(missing_ok=True)
        raise


def add_file(conn, cfg: Config, filename: str, fileobj: BinaryIO) -> tuple[int, bool]:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        kind, name = "pdf", "doc.pdf"
    elif ext in cfg.office_extensions:
        kind, name = "office", f"original{ext}"
    else:
        raise Rejected(f"{filename}: only .pdf and {', '.join(sorted(cfg.office_extensions))} files")
    tmp_dir = cfg.data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / uuid.uuid4().hex
    h, size, limit = hashlib.sha256(), 0, cfg.max_upload_mb * 1024 * 1024
    try:
        with open(tmp, "wb") as f:
            while chunk := fileobj.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise Rejected(f"{filename}: larger than {cfg.max_upload_mb} MB")
                h.update(chunk)
                f.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return _insert(conn, cfg, kind, filename, "sha256:" + h.hexdigest(), tmp, name)


def normalize_url(url: str) -> str:
    u = urlsplit(url.strip())
    if u.scheme.lower() not in ("http", "https") or not u.hostname:
        raise Rejected(f"{url.strip()}: not an http(s) link")
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path, u.query, ""))


def add_url(conn, url: str) -> tuple[int, bool]:
    url = normalize_url(url)
    return _insert(conn, None, "url", url, "url:" + url, None, None)


# ---------------------------------------------------------------- worker

def embed_pending(deps: Deps, conn, doc: store.Doc) -> int:
    """Embed pages pages_embedded+1 .. page_count. Returns the number of requests sent."""
    cfg = deps.cfg
    budget = None
    if cfg.embed_model.endswith(":free"):
        q = deps.openrouter.free_quota(cached=False)  # one GET /key per claimed document
        if q:
            budget = q["remaining"] - cfg.or_reserve_requests
    with store.qdrant_errors():
        deps.qc.get_collections()                     # Qdrant down -> Paused before any request is spent
    n, requests = doc.pages_embedded, 0
    while n < doc.page_count:
        if budget is not None and budget <= 0:
            raise RateLimited(next_utc_midnight() + 60, "daily free quota reserve reached")
        batch = list(range(n + 1, min(n + cfg.embed_batch_pages, doc.page_count) + 1))
        vecs = deps.embedder.embed_pages([store.page_path(cfg, doc.id, p).read_bytes() for p in batch])
        requests += 1
        store.upsert(deps.qc, cfg, doc.id, batch, vecs)
        n = batch[-1]
        store.set_pages_embedded(conn, doc.id, n)     # resume point + progress in the library
        doc.pages_embedded = n
        if budget is not None:
            budget -= 1
    return requests


def _write(path: Path, data: bytes) -> None:
    """Write then rename, so "the file exists" always means complete."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def convert_doc(deps: Deps, doc: store.Doc, d: Path) -> str | None:
    """Produce doc.pdf (PDF/DOCX documents and file links) or source.jpg (web pages). Returns a warning."""
    cfg = deps.cfg
    original = next(d.glob("original.*"), None)
    if doc.kind == "url" and original is None:
        kind = convert.fetch_direct(deps.http, doc.source, d, max_mb=cfg.max_upload_mb)
        if kind == "pdf":
            log.info("doc %d: direct PDF download", doc.id)
            return
        if kind is None:
            data, clipped = convert.url_to_screenshot(deps.http, cfg, doc.source)
            _write(d / "source.jpg", data)
            log.info("doc %d: screenshot taken%s", doc.id, " (clipped: page too tall for one capture)" * clipped)
            if clipped:
                return f"page too tall to capture in one shot; only the first {cfg.max_web_pages} pages are kept"
            return None
        log.info("doc %d: direct DOCX download", doc.id)
        original = d / "original.docx"
    if original is None:
        raise DocError("the uploaded file is missing; delete the document and add it again")
    _write(d / "doc.pdf", convert.office_to_pdf(deps.http, cfg, original))
    log.info("doc %d: converted %s to PDF", doc.id, original.name)


def process(deps: Deps, conn, doc: store.Doc) -> None:
    cfg = deps.cfg
    d = store.doc_dir(cfg, doc.id)
    d.mkdir(parents=True, exist_ok=True)
    pdf, shot = d / "doc.pdf", d / "source.jpg"
    convert_warning = None
    if not pdf.exists() and not shot.exists():
        convert_warning = convert_doc(deps, doc, d)
    steps = []
    if doc.page_count is None:
        if pdf.exists():
            n, warning = convert.render_pages(pdf, d / "pages", longest_edge=cfg.page_longest_edge_px,
                                              quality=cfg.jpeg_quality, max_pages=cfg.max_pages)
        else:
            n, warning = convert.slice_screenshot(shot, d / "pages", slice_height=cfg.web_slice_height,
                                                  quality=cfg.jpeg_quality, max_pages=cfg.max_web_pages)
        store.set_rendered(conn, doc.id, n, warning or convert_warning)
        doc.page_count = n
        steps.append(f"rendered {n} pages")
    elif doc.pages_embedded:
        log.info("doc %d: %d pages pending", doc.id, doc.page_count - doc.pages_embedded)
    requests = embed_pending(deps, conn, doc)
    steps.append(f"embedded {doc.pages_embedded}/{doc.page_count} in {requests} request(s)")
    log.info("doc %d: %s; done", doc.id, "; ".join(steps))


def _wait_message(conn, doc_id: int, e: RateLimited) -> str:
    row = store.get(conn, doc_id)
    at = datetime.fromtimestamp(e.retry_at).strftime("%H:%M")
    msg = f"{e.reason}; resumes {at}"
    if row and row["page_count"]:
        msg += f" ({row['page_count'] - row['pages_embedded']} of {row['page_count']} pages pending)"
    return msg


def run_one(deps: Deps, conn) -> str:
    """Claim one document and process it. Returns idle | done | waiting | paused | error."""
    doc = store.claim(conn)
    if doc is None:
        return "idle"
    try:
        process(deps, conn, doc)
        store.set_status(conn, doc.id, "done")
        return "done"
    except RateLimited as e:
        msg = _wait_message(conn, doc.id, e)
        store.set_status(conn, doc.id, "queued", msg, e.retry_at)
        log.info("doc %d: waiting: %s", doc.id, msg)
        return "waiting"
    except Paused as e:
        store.set_status(conn, doc.id, "queued", str(e))
        deps.status.paused = str(e)
        log.warning("doc %d: worker paused: %s", doc.id, e)
        return "paused"
    except DocError as e:
        store.set_status(conn, doc.id, "error", str(e))
        log.info("doc %d: error: %s", doc.id, e)
        return "error"
    except Exception as e:
        log.exception("doc %d: unexpected error", doc.id)
        store.set_status(conn, doc.id, "error", f"{type(e).__name__}: {e}")
        return "error"


def worker_loop(deps: Deps, stop: threading.Event, wake: threading.Event | None = None) -> None:
    wake = wake or deps.wake
    conn = deps.connect()
    pause = 60.0
    while not stop.is_set():
        try:
            outcome = run_one(deps, conn)
        except Exception:                             # e.g. SQLite busy; the loop must not die
            log.exception("worker loop error")
            outcome = "idle"
        if outcome == "done":
            pause, deps.status.paused, deps.status.until = 60.0, None, None
        elif outcome == "paused":
            deps.status.until = time.time() + pause
            wake.wait(pause)
            wake.clear()
            pause = min(pause * 2, 1800.0)
        elif outcome == "idle":
            wake.wait(5)
            wake.clear()


# ---------------------------------------------------------------- retry and delete (request thread)

def retry(deps: Deps, conn, doc_id: int) -> str | None:
    if not store.retry(conn, doc_id):
        return "only failed or waiting documents can be retried"
    deps.wake.set()
    return None


def delete(deps: Deps, conn, doc_id: int) -> str | None:
    """Row first (the worker can no longer claim it), then the Qdrant points, then the folder."""
    if not store.delete_row(conn, doc_id):
        return "busy (being processed), try again in a moment" if store.get(conn, doc_id) else None
    try:
        store.delete_points(deps.qc, deps.cfg, doc_id)
    except Paused as e:
        return f"{e}; the rest is cleaned up at the next start"
    shutil.rmtree(store.doc_dir(deps.cfg, doc_id), ignore_errors=True)
    return None


# ---------------------------------------------------------------- worker lock and reembed

def take_lock(cfg: Config):
    """The open lock file, or None if the app or a reembed already holds data/worker.lock."""
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    f = open(cfg.data_dir / "worker.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except BlockingIOError:
        f.close()
        return None


def reembed(cfg: Config, qc: QdrantClient | None = None, confirm: Callable[[str], str] = input) -> int:
    """Drop the collection and queue every rendered document; the next app start re-embeds from the JPEGs."""
    lock = take_lock(cfg)
    if lock is None:
        print("stop the web app first")
        return 1
    with lock:
        conn = store.connect(cfg)
        pages, requests = store.request_estimate(conn, cfg.embed_batch_pages)
        prompt = (f"Re-embed {pages} pages with {cfg.embed_model}: about {requests} requests. "
                  f"This deletes the Qdrant collection '{cfg.qdrant_collection}'. Continue? [y/N] ")
        if confirm(prompt).strip().lower() != "y":
            print("nothing changed")
            return 1
        qc = qc or QdrantClient(url=cfg.qdrant_url, timeout=30)
        try:
            with store.qdrant_errors():
                if qc.collection_exists(cfg.qdrant_collection):
                    qc.delete_collection(cfg.qdrant_collection)
        except Paused as e:
            print(e)
            return 1
        n = conn.execute("""UPDATE documents SET status = 'queued', pages_embedded = 0, message = NULL,
                            next_attempt_at = NULL WHERE page_count IS NOT NULL""").rowcount
        conn.commit()
        print(f"{n} documents queued; start the app (make run) to re-embed them")
        return 0

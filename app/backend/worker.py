"""The worker thread (claim a document, run the pipeline, record the outcome), startup recovery, the worker lock,
and reembed. PLAN.md §5.6, §5.8, §8.3-8.4."""
import fcntl
import logging
import shutil
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import TextIO

from qdrant_client import QdrantClient

from app.backend import store
from app.backend.config import Config
from app.backend.deps import Deps
from app.backend.errors import DocError, Paused, RateLimited
from app.backend.rag import vectors
from app.backend.rag.ingest import process

log = logging.getLogger(__name__)


def _wait_message(conn, doc_id: int, e: RateLimited) -> str:
    row = store.get(conn, doc_id)
    msg = f"{e.reason}; resumes {datetime.fromtimestamp(e.retry_at).strftime('%H:%M')}"
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
    """Until stop: work through the queue; when paused, wait 60 s doubling to 30 min; when idle, wait 5 s.
    deps.wake (a new or retried document) ends any wait early."""
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


def recover(conn, qc: QdrantClient, cfg: Config) -> None:
    """Startup: working -> queued; folders without a row (crash during add or delete) are removed."""
    if n := store.requeue_working(conn):
        log.info("recover: %d working document(s) back to queued", n)
    docs = cfg.data_dir / "docs"
    if not docs.is_dir():
        return
    ids = store.all_ids(conn)
    for d in docs.iterdir():
        if d.is_dir() and d.name.isdigit() and int(d.name) not in ids:
            vectors.delete_points(qc, cfg, int(d.name))
            shutil.rmtree(d, ignore_errors=True)
            log.info("recover: removed orphan folder %s", d)


# ---------------------------------------------------------------- worker lock and reembed

def take_lock(cfg: Config) -> TextIO | None:
    """The open lock file, or None if the app or a reembed already holds data/worker.lock."""
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    f = open(cfg.data_dir / "worker.lock", "w")  # noqa: SIM115 -- held open for the app's lifetime
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
        try:
            vectors.drop_collection(qc or QdrantClient(url=cfg.qdrant_url, timeout=30), cfg)
        except Paused as e:
            print(e)
            return 1
        n = store.requeue_for_reembed(conn)
        print(f"{n} documents queued; start the app (make run) to re-embed them")
        return 0

"""The FastAPI app: startup checks, the worker thread, /api, /files and the built UI.

Run with `uvicorn app.backend.main:app` (one process, no --workers)."""
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from qdrant_client import QdrantClient

from app.backend import api, store, worker
from app.backend.config import check_key, load_config, setup_logging
from app.backend.deps import Deps
from app.backend.errors import Paused
from app.backend.rag import agent, vectors
from app.backend.rag.embedder import OpenRouterEmbedder
from app.backend.rag.openrouter import OpenRouter

log = logging.getLogger(__name__)
UI_DIST = Path(__file__).parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    cfg = load_config()
    check_key(cfg)
    for sub in ("docs", "tmp"):
        (cfg.data_dir / sub).mkdir(parents=True, exist_ok=True)
    lock = worker.take_lock(cfg)
    if lock is None:
        raise SystemExit("another app or reembed is running")
    http = httpx.Client(timeout=330)
    orr = OpenRouter(cfg, http)
    qc = QdrantClient(url=cfg.qdrant_url, timeout=30)
    conn = store.connect(cfg)
    try:
        vectors.check_collection(qc, conn, cfg)
        worker.recover(conn, qc, cfg)
    except Paused as e:
        raise SystemExit(str(e))
    finally:
        conn.close()
    deps = Deps(cfg=cfg, connect=lambda: store.connect(cfg), qc=qc, openrouter=orr,
                embedder=OpenRouterEmbedder(cfg, orr), http=http)
    stop = threading.Event()
    thread = threading.Thread(target=worker.worker_loop, args=(deps, stop), daemon=True, name="worker")
    thread.start()
    app.state.deps, app.state.worker = deps, thread
    app.mount("/files", StaticFiles(directory=cfg.data_dir / "docs"), name="files")
    if not (UI_DIST / "index.html").exists():
        log.warning("app/frontend/dist not built; run `npm run build` in app/frontend (or use the Vite dev server)")
    try:
        async with AsyncSqliteSaver.from_conn_string(str(cfg.data_dir / "agent.db")) as checkpointer:
            app.state.agent = agent.build(deps, checkpointer)    # Research conversations
            yield
    finally:
        stop.set()
        deps.wake.set()
        thread.join(timeout=2)
        lock.close()


app = FastAPI(lifespan=lifespan)
app.include_router(api.router)
app.include_router(agent.router)
if (UI_DIST / "index.html").exists():
    # The built UI, matched after every route and mount. A page load of a client route like /library gets index.html.
    app.frontend("/", directory=UI_DIST)

"""One document through the pipeline: convert -> render -> embed -> upsert. Every step resumes."""
import logging

from app.backend import store
from app.backend.deps import Deps
from app.backend.errors import RateLimited
from app.backend.rag import vectors
from app.backend.rag.convert import convert_doc
from app.backend.rag.openrouter import next_utc_midnight
from app.backend.rag.render import render_pages, slice_screenshot

log = logging.getLogger(__name__)


def process(deps: Deps, conn, doc: store.Doc) -> None:
    """Skips what is already done: convert if neither doc.pdf nor source.jpg exists, render if page_count is
    NULL, then embed from pages_embedded + 1. Raises DocError, Paused or RateLimited."""
    cfg = deps.cfg
    d = store.doc_dir(cfg, doc.id)
    d.mkdir(parents=True, exist_ok=True)
    pdf, shot = d / "doc.pdf", d / "source.jpg"
    convert_warning = None
    if not pdf.exists() and not shot.exists():
        convert_warning = convert_doc(deps.http, cfg, doc, d)
    steps = []
    if doc.page_count is None:
        if pdf.exists():
            n, warning = render_pages(pdf, d / "pages", longest_edge=cfg.page_longest_edge_px,
                                      quality=cfg.jpeg_quality, max_pages=cfg.max_pages)
        else:
            n, warning = slice_screenshot(shot, d / "pages", slice_height=cfg.web_slice_height,
                                          quality=cfg.jpeg_quality, max_pages=cfg.max_web_pages)
        store.set_rendered(conn, doc.id, n, warning or convert_warning)
        doc.page_count = n
        steps.append(f"rendered {n} pages")
    elif doc.pages_embedded:
        log.info("doc %d: %d pages pending", doc.id, doc.page_count - doc.pages_embedded)
    requests = embed_pending(deps, conn, doc)
    steps.append(f"embedded {doc.pages_embedded}/{doc.page_count} in {requests} request(s)")
    log.info("doc %d: %s; done", doc.id, "; ".join(steps))


def embed_pending(deps: Deps, conn, doc: store.Doc) -> int:
    """Embed pages pages_embedded+1 .. page_count, EMBED_BATCH_PAGES per request. Returns the number of requests."""
    cfg = deps.cfg
    budget = None
    if cfg.embed_model.endswith(":free"):
        q = deps.openrouter.free_quota(cached=False)  # one GET /key per claimed document
        if q:
            budget = q["remaining"] - cfg.or_reserve_requests
    vectors.check_reachable(deps.qc)                  # Qdrant down -> Paused before any request is spent
    n, requests = doc.pages_embedded, 0
    while n < doc.page_count:
        if budget is not None and budget <= 0:
            raise RateLimited(next_utc_midnight() + 60, "daily free quota reserve reached")
        batch = list(range(n + 1, min(n + cfg.embed_batch_pages, doc.page_count) + 1))
        vecs = deps.embedder.embed_pages([store.page_path(cfg, doc.id, p).read_bytes() for p in batch])
        requests += 1
        vectors.upsert(deps.qc, cfg, doc.id, batch, vecs)
        n = batch[-1]
        store.set_pages_embedded(conn, doc.id, n)     # resume point + progress in the library
        doc.pages_embedded = n
        if budget is not None:
            budget -= 1
    return requests

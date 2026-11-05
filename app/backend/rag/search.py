"""Search: embed the question, find the best pages grouped by document."""
import time
from dataclasses import asdict, dataclass
from datetime import datetime

from app.backend import store
from app.backend.deps import Deps
from app.backend.errors import DocError, Paused, RateLimited
from app.backend.rag import vectors
from app.backend.rag.openrouter import next_utc_midnight


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
        return store.page_url(self.doc_id, self.page_no)

    def to_json(self) -> dict:
        return {**asdict(self), "image_url": self.image_url}


def user_message(e: DocError | Paused | RateLimited) -> str:
    """What the user sees when a search or an answer fails. Interactive requests are never retried."""
    if not isinstance(e, RateLimited):
        return str(e)
    if "daily" in e.reason:
        return f"Daily free limit reached; resets {datetime.fromtimestamp(next_utc_midnight()).strftime('%H:%M')}"
    return f"Rate-limited, try again in {max(int(e.retry_at - time.time()), 1)} s"


def search(deps: Deps, conn, q: str) -> list[list[Hit]] | str:
    """One list of hits per document, best document first; or a message for the user."""
    q = q.strip()
    if not q:
        return "Type a question first."
    try:
        if not vectors.collection_exists(deps.qc, deps.cfg):
            return "No documents yet."
        groups = vectors.search_groups(deps.qc, deps.cfg, deps.embed_query(q))
    except (DocError, Paused, RateLimited) as e:
        return user_message(e)
    rows = store.by_ids(conn, [g.id for g in groups])       # a hit without a row was just deleted: dropped
    return [[Hit(g.id, h.payload["page"], h.score, rows[g.id]["title"], rows[g.id]["kind"], rows[g.id]["source"],
                 store.file_url(deps.cfg, g.id) or "") for h in g.hits] for g in groups if g.id in rows]

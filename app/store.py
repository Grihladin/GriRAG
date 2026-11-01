"""SQLite (catalog + job state) and Qdrant (page vectors). PLAN.md §4."""
import logging
import math
import shutil
import sqlite3
import time
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app import DocError, Paused
from app.config import Config

log = logging.getLogger("app.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  kind            TEXT NOT NULL CHECK (kind IN ('pdf', 'office', 'url')),
  source          TEXT NOT NULL,
  title           TEXT NOT NULL,
  dedup_key       TEXT NOT NULL UNIQUE,
  status          TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'working', 'done', 'error')),
  message         TEXT,
  warning         TEXT,
  next_attempt_at INTEGER,
  page_count      INTEGER,
  pages_embedded  INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class Doc:
    id: int
    kind: str
    source: str
    page_count: int | None
    pages_embedded: int


def connect(cfg: Config) -> sqlite3.Connection:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cfg.data_dir / "app.db", timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(SCHEMA)
    return conn


def doc_dir(cfg: Config, doc_id: int) -> Path:
    return cfg.data_dir / "docs" / str(doc_id)


def page_path(cfg: Config, doc_id: int, page_no: int) -> Path:
    return doc_dir(cfg, doc_id) / "pages" / f"{page_no:04d}.jpg"


# ---------------------------------------------------------------- SQLite

def get(conn, doc_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()


def by_dedup(conn, key: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE dedup_key = ?", (key,)).fetchone()


def list_docs(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM documents ORDER BY id DESC").fetchall()


def claim(conn, now: float | None = None) -> Doc | None:
    row = conn.execute(
        """UPDATE documents SET status = 'working', message = NULL
           WHERE id = (SELECT id FROM documents
                       WHERE status = 'queued' AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
                       ORDER BY id LIMIT 1)
           RETURNING id, kind, source, page_count, pages_embedded""",
        {"now": int(time.time() if now is None else now)}).fetchone()
    conn.commit()
    return Doc(**dict(row)) if row else None


def set_rendered(conn, doc_id: int, page_count: int, warning: str | None) -> None:
    conn.execute("UPDATE documents SET page_count = ?, warning = ? WHERE id = ?", (page_count, warning, doc_id))
    conn.commit()


def set_pages_embedded(conn, doc_id: int, n: int) -> None:
    conn.execute("UPDATE documents SET pages_embedded = ? WHERE id = ?", (n, doc_id))
    conn.commit()


def set_status(conn, doc_id: int, status: str, message: str | None = None,
               next_attempt_at: float | None = None) -> None:
    conn.execute("UPDATE documents SET status = ?, message = ?, next_attempt_at = ? WHERE id = ?",
                 (status, message, None if next_attempt_at is None else int(next_attempt_at), doc_id))
    conn.commit()


def retry(conn, doc_id: int, now: float | None = None) -> bool:
    cur = conn.execute(
        """UPDATE documents SET status = 'queued', message = NULL, next_attempt_at = NULL
           WHERE id = ? AND (status = 'error' OR (status = 'queued' AND next_attempt_at > ?))""",
        (doc_id, int(time.time() if now is None else now)))
    conn.commit()
    return cur.rowcount == 1


def delete_row(conn, doc_id: int) -> bool:
    cur = conn.execute("DELETE FROM documents WHERE id = ? AND status != 'working'", (doc_id,))
    conn.commit()
    return cur.rowcount == 1


def request_estimate(conn, batch: int) -> tuple[int, int]:
    """(pages embedded or to embed, requests to embed them all) over every rendered document."""
    counts = [r[0] for r in conn.execute("SELECT page_count FROM documents WHERE page_count IS NOT NULL")]
    return sum(counts), sum(math.ceil(c / batch) for c in counts)


def recover(conn, qc: QdrantClient, cfg: Config) -> None:
    """Startup: working -> queued; folders without a row (crash during add or delete) are removed."""
    n = conn.execute("UPDATE documents SET status = 'queued' WHERE status = 'working'").rowcount
    conn.commit()
    if n:
        log.info("recover: %d working document(s) back to queued", n)
    docs = cfg.data_dir / "docs"
    if not docs.is_dir():
        return
    ids = {r[0] for r in conn.execute("SELECT id FROM documents")}
    for d in docs.iterdir():
        if d.is_dir() and d.name.isdigit() and int(d.name) not in ids:
            delete_points(qc, cfg, int(d.name))
            shutil.rmtree(d, ignore_errors=True)
            log.info("recover: removed orphan folder %s", d)


# ---------------------------------------------------------------- Qdrant

@contextmanager
def qdrant_errors():
    """Connection problems pause the worker; Qdrant rejecting the data fails the document."""
    try:
        yield
    except (ResponseHandlingException, httpx.TransportError) as e:
        raise Paused("Qdrant is not running: make up") from e
    except UnexpectedResponse as e:
        raise DocError(f"Qdrant: {e}") from e
    except ValueError as e:                       # local mode reports bad vectors as ValueError
        raise DocError(f"Qdrant: {e}") from e


def collection_exists(qc: QdrantClient, cfg: Config) -> bool:
    with qdrant_errors():
        return qc.collection_exists(cfg.qdrant_collection)


def check_collection(qc: QdrantClient, conn, cfg: Config) -> None:
    """Exit if the stored vectors no longer match the config, or were lost (PLAN.md §4.2)."""
    pages, requests = request_estimate(conn, cfg.embed_batch_pages)
    if collection_exists(qc, cfg):
        meta = qc.get_collection(cfg.qdrant_collection).config.metadata or {}
        for key, want in (("embed_model", cfg.embed_model), ("passage_mode", cfg.passage_mode)):
            if meta.get(key) != want:
                raise SystemExit(f"{key.upper() if key == 'embed_model' else 'Passage mode'} changed from "
                                 f"{meta.get(key)} to {want}: run 'make reembed' (≈ {requests} requests) "
                                 f"or revert .env")
        return
    embedded = conn.execute("SELECT COALESCE(SUM(pages_embedded), 0) FROM documents").fetchone()[0]
    if embedded:
        raise SystemExit(f"Qdrant collection '{cfg.qdrant_collection}' is missing but {embedded} pages were "
                         f"embedded: run 'make reembed' (≈ {requests} requests)")


def upsert(qc: QdrantClient, cfg: Config, doc_id: int, pages: list[int], vecs: list[list[float]]) -> None:
    with qdrant_errors():
        if not qc.collection_exists(cfg.qdrant_collection):
            dim = len(vecs[0])
            qc.create_collection(cfg.qdrant_collection,
                                 vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
                                 metadata={"embed_model": cfg.embed_model, "dim": dim,
                                           "passage_mode": cfg.passage_mode})
            with warnings.catch_warnings():       # local mode warns that payload indexes do nothing
                warnings.simplefilter("ignore")
                qc.create_payload_index(cfg.qdrant_collection, field_name="doc_id",
                                        field_schema=models.PayloadSchemaType.INTEGER)
        qc.upsert(cfg.qdrant_collection, wait=True, points=[
            models.PointStruct(id=doc_id * 10000 + p, vector=v, payload={"doc_id": doc_id, "page": p})
            for p, v in zip(pages, vecs)])


def search_groups(qc: QdrantClient, cfg: Config, vec: list[float]) -> list:
    with qdrant_errors():
        return qc.query_points_groups(cfg.qdrant_collection, group_by="doc_id", query=vec,
                                      limit=cfg.search_groups, group_size=max(cfg.answer_pages, 3), with_payload=True).groups


def delete_points(qc: QdrantClient, cfg: Config, doc_id: int) -> None:
    with qdrant_errors():
        if qc.collection_exists(cfg.qdrant_collection):
            qc.delete(cfg.qdrant_collection, points_selector=models.FilterSelector(filter=models.Filter(
                must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])))

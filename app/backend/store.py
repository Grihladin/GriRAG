"""The SQLite catalog (one `documents` table: catalog + job state) and the document folders."""
import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from app.backend.config import Config

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
    """The columns the worker needs for one claimed document."""
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


# ---------------------------------------------------------------- folders: data/docs/{id}/

def doc_dir(cfg: Config, doc_id: int) -> Path:
    return cfg.data_dir / "docs" / str(doc_id)


def page_path(cfg: Config, doc_id: int, page_no: int) -> Path:
    return doc_dir(cfg, doc_id) / "pages" / f"{page_no:04d}.jpg"


def page_url(doc_id: int, page_no: int) -> str:
    return f"/files/{doc_id}/pages/{page_no:04d}.jpg"


def file_url(cfg: Config, doc_id: int) -> str | None:
    """The whole document: doc.pdf (PDF, DOCX, PDF links), or source.jpg (screenshotted web pages); None until it exists."""
    for name in ("doc.pdf", "source.jpg"):
        if (doc_dir(cfg, doc_id) / name).exists():
            return f"/files/{doc_id}/{name}"
    return None


# ---------------------------------------------------------------- reads

def get(conn, doc_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()


def by_dedup(conn, key: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE dedup_key = ?", (key,)).fetchone()


def by_ids(conn, ids: list[int]) -> dict[int, sqlite3.Row]:
    rows = conn.execute(f"SELECT * FROM documents WHERE id IN ({','.join('?' * len(ids))})", ids)
    return {r["id"]: r for r in rows}


def list_docs(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM documents ORDER BY id DESC").fetchall()


def all_ids(conn) -> set[int]:
    return {r[0] for r in conn.execute("SELECT id FROM documents")}


def pages_embedded(conn) -> int:
    return conn.execute("SELECT COALESCE(SUM(pages_embedded), 0) FROM documents").fetchone()[0]


def request_estimate(conn, batch: int) -> tuple[int, int]:
    """(pages embedded or to embed, requests to embed them all) over every rendered document."""
    counts = [r[0] for r in conn.execute("SELECT page_count FROM documents WHERE page_count IS NOT NULL")]
    return sum(counts), sum(math.ceil(c / batch) for c in counts)


# ---------------------------------------------------------------- writes

def insert(conn, kind: str, source: str, dedup_key: str) -> int:
    """A queued document titled by its source; not committed (the caller commits once its files are in place)."""
    return conn.execute("INSERT INTO documents (kind, source, title, dedup_key) VALUES (?, ?, ?, ?)",
                        (kind, source, source, dedup_key)).lastrowid


def claim(conn, now: float | None = None) -> Doc | None:
    """The oldest queued document that is not waiting, now 'working'."""
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
    """Compare-and-set: only a failed or waiting document goes back to the queue."""
    cur = conn.execute(
        """UPDATE documents SET status = 'queued', message = NULL, next_attempt_at = NULL
           WHERE id = ? AND (status = 'error' OR (status = 'queued' AND next_attempt_at > ?))""",
        (doc_id, int(time.time() if now is None else now)))
    conn.commit()
    return cur.rowcount == 1


def delete_row(conn, doc_id: int) -> bool:
    """Compare-and-set: a document the worker is processing is not deleted."""
    cur = conn.execute("DELETE FROM documents WHERE id = ? AND status != 'working'", (doc_id,))
    conn.commit()
    return cur.rowcount == 1


def requeue_working(conn) -> int:
    """Startup: documents a crash left 'working' go back to the queue."""
    n = conn.execute("UPDATE documents SET status = 'queued' WHERE status = 'working'").rowcount
    conn.commit()
    return n


def requeue_for_reembed(conn) -> int:
    """Every rendered document is queued with no pages embedded; its page images are kept."""
    n = conn.execute("""UPDATE documents SET status = 'queued', pages_embedded = 0, message = NULL,
                        next_attempt_at = NULL WHERE page_count IS NOT NULL""").rowcount
    conn.commit()
    return n

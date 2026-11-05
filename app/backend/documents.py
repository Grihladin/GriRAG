"""Adding, retrying and deleting documents (request thread; the worker does the rest)."""
import hashlib
import logging
import os
import shutil
import sqlite3
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit, urlunsplit

from app.backend import store
from app.backend.config import Config
from app.backend.deps import Deps
from app.backend.errors import Paused
from app.backend.rag import vectors

log = logging.getLogger(__name__)


class Rejected(ValueError):
    """Not added: wrong file type, too large, or not an http(s) link. The message is shown to the user."""


# ---------------------------------------------------------------- adding

def _insert(conn, cfg: Config, kind: str, source: str, key: str, tmp: Path | None = None, name: str | None = None
            ) -> tuple[int, bool]:
    """(doc_id, created). An upload in `tmp` moves to data/docs/{id}/{name}; a duplicate's is deleted."""
    if row := store.by_dedup(conn, key):
        if tmp:
            tmp.unlink(missing_ok=True)
        return row["id"], False
    d = None
    try:
        doc_id = store.insert(conn, kind, source, key)
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
    """Stream the upload to data/tmp while hashing it; the SHA-256 is the dedup key."""
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
    """Lower-case scheme and host, no fragment; anything but http(s) is rejected."""
    u = urlsplit(url.strip())
    if u.scheme.lower() not in ("http", "https") or not u.hostname:
        raise Rejected(f"{url.strip()}: not an http(s) link")
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path, u.query, ""))


def add_url(conn, url: str) -> tuple[int, bool]:
    url = normalize_url(url)
    return _insert(conn, None, "url", url, "url:" + url)


def add_all(conn, cfg: Config, files: list[tuple[str, BinaryIO]], urls: list[str]) -> dict:
    """Add every file and link; each one is added, a duplicate (with its title and status), or rejected."""
    result = {"added": 0, "duplicates": [], "rejected": []}

    def record(add: Callable[..., tuple[int, bool]], *args) -> None:
        try:
            doc_id, created = add(conn, *args)
        except Rejected as e:
            log.info("rejected: %s", e)
            result["rejected"].append(str(e))
            return
        if created:
            result["added"] += 1
        else:
            r = store.get(conn, doc_id)
            result["duplicates"].append({"id": doc_id, "title": r["title"], "status": r["status"]})

    for filename, fileobj in files:
        record(add_file, cfg, filename, fileobj)
    for url in urls:
        record(add_url, url)
    return result


# ---------------------------------------------------------------- retry and delete

def retry(deps: Deps, conn, doc_id: int) -> str | None:
    """None, or the reason it was refused."""
    if not store.retry(conn, doc_id):
        return "only failed or waiting documents can be retried"
    deps.wake.set()
    return None


def delete(deps: Deps, conn, doc_id: int) -> str | None:
    """Row first (the worker can no longer claim it), then the Qdrant points, then the folder. None, or a message."""
    if not store.delete_row(conn, doc_id):
        return "busy (being processed), try again in a moment" if store.get(conn, doc_id) else None
    try:
        vectors.delete_points(deps.qc, deps.cfg, doc_id)
    except Paused as e:
        return f"{e}; the rest is cleaned up at the next start"
    shutil.rmtree(store.doc_dir(deps.cfg, doc_id), ignore_errors=True)
    return None

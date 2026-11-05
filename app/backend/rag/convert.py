"""Converting a document to doc.pdf or source.jpg: direct link downloads and Gotenberg calls."""
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.backend import store
from app.backend.config import Config
from app.backend.errors import DocError, Paused

log = logging.getLogger(__name__)

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Makes lazy images eager and scrolls one viewport at a time (at most 40 steps, the MAX_WEB_PAGES cap), then
# returns to the top and waits up to 5 s for fonts and images. Never throws, always returns true.
SCROLL_JS = ("(async () => { try { document.querySelectorAll('img[loading=\"lazy\"]').forEach((i) => { i.loading = "
             "'eager'; }); const step = window.innerHeight || 800; for (let y = 0, n = 0; y < document.documentElement"
             ".scrollHeight && n < 40; y += step, n++) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, "
             "150)); } window.scrollTo(0, 0); const pending = Array.from(document.images).filter((i) => !i.complete)"
             ".map((i) => new Promise((r) => { i.addEventListener('load', r, { once: true }); i.addEventListener("
             "'error', r, { once: true }); })); await Promise.race([Promise.all([document.fonts.ready, ...pending]), "
             "new Promise((r) => setTimeout(r, 5000))]); } catch (e) {} return true; })()")


def web_shot(cfg: Config, url: str) -> dict:
    """Form fields for POST /forms/chromium/screenshot/url (Gotenberg 8.39.0). skipNetworkAlmostIdleEvent=false is
    not sent: with it even example.com ran into the 300 s time limit; SCROLL_JS does the waiting."""
    return {"url": url, "width": str(cfg.web_viewport_width), "height": str(cfg.web_slice_height),
            "clip": "false", "format": "jpeg", "quality": str(cfg.jpeg_quality), "emulatedMediaType": "screen",
            "waitForExpression": SCROLL_JS}


# ---------------------------------------------------------------- links that are files

def fetch_direct(http: httpx.Client, url: str, doc_dir: Path, *, max_mb: int = 200) -> str | None:
    """Download a link that answers with a PDF or DOCX file. Returns "pdf" | "office" | None (= screenshot it)."""
    try:
        with http.stream("GET", url, follow_redirects=True, timeout=30) as r:
            if r.status_code != 200:
                return None
            ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
            path = urlsplit(str(r.url)).path.lower()
            octet = ctype == "application/octet-stream"
            if ctype == "application/pdf" or (octet and path.endswith(".pdf")):
                kind, name = "pdf", "doc.pdf"
            elif ctype == DOCX_TYPE or (octet and path.endswith(".docx")):
                kind, name = "office", "original.docx"
            else:
                return None
            tmp, size = doc_dir / f"{name}.tmp", 0
            try:
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > max_mb * 1024 * 1024:
                            raise DocError(f"download larger than {max_mb} MB")
                        f.write(chunk)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
            os.replace(tmp, doc_dir / name)
            return kind
    except httpx.HTTPError:
        return None


# ---------------------------------------------------------------- Gotenberg

def _gotenberg(http: httpx.Client, cfg: Config, route: str, files: list) -> bytes:
    try:
        r = http.post(cfg.gotenberg_url + route, files=files, timeout=330)
    except httpx.TransportError as e:
        raise Paused("Gotenberg is not running: make up") from e
    if r.status_code == 200:
        return r.content
    body = r.text.strip()[:500]
    if r.status_code == 403:
        raise DocError("URL blocked or host not resolvable (DNS failure, private address, or deny list)")
    if r.status_code == 409:
        raise DocError(f"the page answered with an error status: {body}")
    if r.status_code == 429:
        raise Paused("Gotenberg is busy (queue full)")
    raise DocError(f"Gotenberg {r.status_code}: {body}")


def url_to_screenshot(http: httpx.Client, cfg: Config, url: str) -> tuple[bytes, bool]:
    """Full-page JPEG, WEB_VIEWPORT_WIDTH wide, and whether it had to be clipped. Every field goes as a form field.

    Chromium returns an empty image (HTTP 200, 0 bytes) for pages too tall to capture in one shot.
    Then only the top MAX_WEB_PAGES slices are captured with clip=true; that makes the viewport that tall too."""
    fields = web_shot(cfg, url)
    route = "/forms/chromium/screenshot/url"
    if data := _gotenberg(http, cfg, route, [(k, (None, v)) for k, v in fields.items()]):
        return data, False
    fields.update(clip="true", height=str(cfg.max_web_pages * cfg.web_slice_height))
    if data := _gotenberg(http, cfg, route, [(k, (None, v)) for k, v in fields.items()]):
        return data, True
    raise DocError("Gotenberg returned an empty screenshot")


def office_to_pdf(http: httpx.Client, cfg: Config, path: Path) -> bytes:
    """LibreOffice picks the format from the file extension, so the original name is kept."""
    return _gotenberg(http, cfg, "/forms/libreoffice/convert", [("files", (path.name, path.read_bytes()))])


# ---------------------------------------------------------------- one document

def write_atomic(path: Path, data: bytes) -> None:
    """Write then rename, so "the file exists" always means complete."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def convert_doc(http: httpx.Client, cfg: Config, doc: store.Doc, d: Path) -> str | None:
    """Produce doc.pdf (PDF/DOCX documents and file links) or source.jpg (web pages) in d. Returns a warning."""
    original = next(d.glob("original.*"), None)
    if doc.kind == "url" and original is None:
        kind = fetch_direct(http, doc.source, d, max_mb=cfg.max_upload_mb)
        if kind == "pdf":
            log.info("doc %d: direct PDF download", doc.id)
            return None
        if kind is None:
            data, clipped = url_to_screenshot(http, cfg, doc.source)
            write_atomic(d / "source.jpg", data)
            log.info("doc %d: screenshot taken%s", doc.id, " (clipped: page too tall for one capture)" * clipped)
            if clipped:
                return f"page too tall to capture in one shot; only the first {cfg.max_web_pages} pages are kept"
            return None
        log.info("doc %d: direct DOCX download", doc.id)
        original = d / "original.docx"
    if original is None:
        raise DocError("the uploaded file is missing; delete the document and add it again")
    write_atomic(d / "doc.pdf", office_to_pdf(http, cfg, original))
    log.info("doc %d: converted %s to PDF", doc.id, original.name)
    return None

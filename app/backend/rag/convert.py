"""Converting and rendering: Gotenberg calls, direct link downloads, PyMuPDF page rendering. PLAN.md §5.2-5.3."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pymupdf

from app.backend.config import Config
from app.backend.errors import DocError, Paused

pymupdf.TOOLS.mupdf_display_errors(False)        # broken files become DocError, not stderr noise

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIN_SLICE_PX = 28

# Makes lazy images eager and scrolls one viewport at a time (at most 40 steps, the MAX_WEB_PAGES cap), then
# returns to the top and waits up to 5 s for fonts and images. Never throws, always returns true (PLAN.md §5.2).
SCROLL_JS = ("(async () => { try { document.querySelectorAll('img[loading=\"lazy\"]').forEach((i) => { i.loading = "
             "'eager'; }); const step = window.innerHeight || 800; for (let y = 0, n = 0; y < document.documentElement"
             ".scrollHeight && n < 40; y += step, n++) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, "
             "150)); } window.scrollTo(0, 0); const pending = Array.from(document.images).filter((i) => !i.complete)"
             ".map((i) => new Promise((r) => { i.addEventListener('load', r, { once: true }); i.addEventListener("
             "'error', r, { once: true }); })); await Promise.race([Promise.all([document.fonts.ready, ...pending]), "
             "new Promise((r) => setTimeout(r, 5000))]); } catch (e) {} return true; })()")


def web_shot(cfg: Config, url: str) -> dict:
    """Form fields for POST /forms/chromium/screenshot/url (Gotenberg 8.39.0). skipNetworkAlmostIdleEvent=false is
    not sent: with it even example.com ran into the 300 s time limit (PLAN.md §15); SCROLL_JS does the waiting."""
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

    Chromium returns an empty image (HTTP 200, 0 bytes) for pages too tall to capture in one shot (PLAN.md §15).
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


def render_pages(pdf: Path, out_dir: Path, *, longest_edge: int, quality: int, max_pages: int
                 ) -> tuple[int, str | None]:
    """One JPEG per PDF page, longest edge `longest_edge` px. Returns (page_count, warning)."""
    try:
        doc = pymupdf.open(pdf, filetype="pdf")
    except Exception as e:
        raise DocError("not a readable PDF") from e
    with doc:
        if doc.needs_pass:
            raise DocError("password-protected PDF")
        if not 0 < doc.page_count <= max_pages:
            raise DocError(f"{doc.page_count} pages (limit {max_pages})")
        out_dir.mkdir(parents=True, exist_ok=True)
        tall = []
        for no, page in enumerate(doc, start=1):            # one page in memory at a time
            w, h = page.rect.width, page.rect.height
            z = longest_edge / max(w, h)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
            pix.save(out_dir / f"{no:04d}.jpg", jpg_quality=quality)
            if max(w, h) > 3 * min(w, h):
                tall.append(no)
        return doc.page_count, (f"pages {tall} are very tall; text may be unreadable" if tall else None)


def square_jpeg(jpeg: bytes, quality: int) -> bytes:
    """The page centred on a white square. The free NVIDIA embedder fails every time on some page shapes
    (US Letter, 852-880 x 1120) but has never failed on squares (PLAN.md §15); only its input is padded."""
    src = pymupdf.Pixmap(jpeg)
    s = max(src.width, src.height)
    if src.width == src.height:
        return jpeg
    canvas = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, s, s), False)
    canvas.clear_with(255)                           # white; set_rect is ~1 s per page
    src.set_origin((s - src.width) // 2, (s - src.height) // 2)
    canvas.copy(src, src.irect)
    return canvas.tobytes("jpeg", jpg_quality=quality)


def slice_screenshot(src: Path, out_dir: Path, *, slice_height: int, quality: int, max_pages: int
                     ) -> tuple[int, str | None]:
    """Cut a full-page screenshot into slice_height rows, top to bottom, no overlap. Returns (page_count, warning)."""
    try:
        img = pymupdf.Pixmap(str(src))
    except Exception as e:
        raise DocError("not a readable screenshot") from e
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = img.width, img.height
    n = 0
    for y in range(0, h, slice_height):
        if h - y < MIN_SLICE_PX or n == max_pages:       # drop a strip under 28 px; keep the first max_pages
            break
        n += 1
        tile = pymupdf.Pixmap(img.colorspace, pymupdf.IRect(0, y, w, min(y + slice_height, h)), img.alpha)
        tile.copy(img, tile.irect)
        tile.set_origin(0, 0)
        tile.save(out_dir / f"{n:04d}.jpg", jpg_quality=quality)
    if n == 0:
        raise DocError("empty screenshot")
    cut = h - n * slice_height >= MIN_SLICE_PX
    return n, (f"page is {h} px tall; only the first {n} pages are kept" if cut else None)

"""Page images with PyMuPDF: PDF pages, web screenshot slices, and square padding for the embedder. PLAN.md §5.3-5.4."""
from pathlib import Path

import pymupdf

from app.backend.errors import DocError

pymupdf.TOOLS.mupdf_display_errors(False)        # broken files become DocError, not stderr noise

MIN_SLICE_PX = 28


def page_pixmap(page: pymupdf.Page, longest_edge: int) -> pymupdf.Pixmap:
    """The page scaled so its longest edge is `longest_edge` px, on white."""
    z = longest_edge / max(page.rect.width, page.rect.height)
    return page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)


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
            page_pixmap(page, longest_edge).save(out_dir / f"{no:04d}.jpg", jpg_quality=quality)
            w, h = page.rect.width, page.rect.height
            if max(w, h) > 3 * min(w, h):
                tall.append(no)
        return doc.page_count, (f"pages {tall} are very tall; text may be unreadable" if tall else None)


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


def square_jpeg(jpeg: bytes, quality: int) -> bytes:
    """The page centred on a white square. The free NVIDIA embedder fails every time on some page shapes
    (US Letter, 852-880 x 1120) but has never failed on squares (PLAN.md §15); only its input is padded."""
    src = pymupdf.Pixmap(jpeg)
    if src.width == src.height:
        return jpeg
    s = max(src.width, src.height)
    canvas = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, s, s), False)
    canvas.clear_with(255)                           # white; set_rect is ~1 s per page
    src.set_origin((s - src.width) // 2, (s - src.height) // 2)
    canvas.copy(src, src.irect)
    return canvas.tobytes("jpeg", jpg_quality=quality)

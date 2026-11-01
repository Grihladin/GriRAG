import pymupdf
import pytest

from app.backend.errors import DocError
from app.backend.rag.render import render_pages, square_jpeg
from tests.conftest import FIXTURES, make_pdf

KW = {"longest_edge": 1536, "quality": 85, "max_pages": 500}


def size(p):
    pix = pymupdf.Pixmap(str(p))
    return pix.width, pix.height


def test_sample_pdf_three_pages(tmp_path):
    n, warning = render_pages(FIXTURES / "sample.pdf", tmp_path, **KW)
    assert (n, warning) == (3, None)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["0001.jpg", "0002.jpg", "0003.jpg"]
    assert size(tmp_path / "0001.jpg") == (1187, 1536)     # US Letter
    assert size(tmp_path / "0002.jpg") == (1086, 1536)     # A4


@pytest.mark.parametrize("name,msg", [("encrypted.pdf", "password"), ("not_a_pdf.pdf", "not a readable PDF")])
def test_unreadable(tmp_path, name, msg):
    with pytest.raises(DocError, match=msg):
        render_pages(FIXTURES / name, tmp_path / "out", **KW)


def test_max_pages(tmp_path):
    pdf = make_pdf(tmp_path / "four.pdf", 4)
    with pytest.raises(DocError, match=r"4 pages \(limit 3\)"):
        render_pages(pdf, tmp_path / "out", **{**KW, "max_pages": 3})


def test_tall_page_warning(tmp_path):
    pdf = make_pdf(tmp_path / "tall.pdf", 1, size=(200, 2000))
    n, warning = render_pages(pdf, tmp_path / "out", **KW)
    assert n == 1 and "pages [1] are very tall" in warning
    assert size(tmp_path / "out" / "0001.jpg") == (154, 1536)


def test_square_jpeg_pads_and_centres():
    src = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 300), False)
    src.clear_with(0)
    out = pymupdf.Pixmap(square_jpeg(src.tobytes("jpeg"), 85))
    assert (out.width, out.height) == (300, 300)
    assert out.pixel(10, 150)[0] > 240 and out.pixel(150, 150)[0] < 15    # white margin, black page centred
    sq = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False).tobytes("jpeg")
    assert square_jpeg(sq, 85) is sq                                         # squares are sent as they are


# ---------------------------------------------------------------- slicing web screenshots

from app.backend.rag.render import slice_screenshot

SKW = {"slice_height": 1120, "quality": 85, "max_pages": 40}


def screenshot(path, w, h):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    pix.clear_with(255)
    for y in range(0, h, 1120):                    # mark the first row of each slice to check positions
        pix.set_rect(pymupdf.IRect(0, y, w, min(y + 20, h)), (0, 0, 0))
    pix.save(path, jpg_quality=95)
    return path


def heights(out):
    return [pymupdf.Pixmap(str(p)).height for p in sorted(out.iterdir())]


def test_slice_2300(tmp_path):
    n, warning = slice_screenshot(screenshot(tmp_path / "s.jpg", 1120, 2300), tmp_path / "out", **SKW)
    assert (n, warning) == (3, None)
    assert heights(tmp_path / "out") == [1120, 1120, 60]
    for p in sorted((tmp_path / "out").iterdir()):   # every slice starts at a marked row
        pix = pymupdf.Pixmap(str(p))
        assert pix.width == 1120 and pix.pixel(500, 5)[0] < 60 and pix.pixel(500, 40)[0] > 200


def test_slice_drops_small_remnant(tmp_path):
    n, warning = slice_screenshot(screenshot(tmp_path / "s.jpg", 1120, 2250), tmp_path / "out", **SKW)
    assert (n, warning) == (2, None)
    assert heights(tmp_path / "out") == [1120, 1120]


def test_slice_cut_at_max_pages(tmp_path):
    n, warning = slice_screenshot(screenshot(tmp_path / "s.jpg", 1120, 1120 * 3 + 500), tmp_path / "out",
                                  **{**SKW, "max_pages": 2})
    assert n == 2 and warning == "page is 3860 px tall; only the first 2 pages are kept"


def test_slice_too_small(tmp_path):
    with pytest.raises(DocError, match="empty screenshot"):
        slice_screenshot(screenshot(tmp_path / "s.jpg", 1120, 20), tmp_path / "out", **SKW)


def test_slice_unreadable(tmp_path):
    (tmp_path / "s.jpg").write_bytes(b"not a jpeg")
    with pytest.raises(DocError, match="not a readable screenshot"):
        slice_screenshot(tmp_path / "s.jpg", tmp_path / "out", **SKW)

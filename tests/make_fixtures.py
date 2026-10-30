"""One-off fixture generator; its outputs are committed.

uv run --with python-docx==1.2.0 python tests/make_fixtures.py tests/fixtures
"""
import io
import random
import sys
from pathlib import Path

import pymupdf

LETTER, A4 = (612, 792), (595, 842)


def text_page(doc, size, title, body):
    p = doc.new_page(width=size[0], height=size[1])
    p.insert_text((60, 90), title, fontsize=22)
    p.insert_textbox(pymupdf.Rect(60, 120, size[0] - 60, size[1] - 60), body, fontsize=12)
    return p


def sample_pdf(path):
    with pymupdf.open() as doc:
        text_page(doc, LETTER, "Travel notes", "The capital of Freedonia is Plumbury. "
                  "Plumbury sits on the river Fenn and is known for its markets and its old stone bridge.")
        p = doc.new_page(width=A4[0], height=A4[1])
        p.insert_text((60, 80), "INVOICE No. 2026-117", fontsize=20)
        rows = [("Item", "Qty", "Price"), ("Widget A", "10", "1,200 EUR"), ("Widget B", "4", "2,000 EUR"),
                ("Shipping", "1", "1,112 EUR"), ("Total", "", "4,312 EUR")]
        y = 150
        for a, b, c in rows:
            p.draw_rect(pymupdf.Rect(60, y - 16, 535, y + 6), color=(0, 0, 0), width=0.6)
            for x, t in ((66, a), (330, b), (430, c)):
                p.insert_text((x, y), t, fontsize=12)
            y += 22
        p = doc.new_page(width=A4[0], height=A4[1])
        p.insert_text((60, 80), "Revenue by quarter 2025", fontsize=20)
        for i, (q, v) in enumerate((("Q1", 120), ("Q2", 180), ("Q3", 150), ("Q4", 240))):
            x = 100 + i * 110
            p.draw_rect(pymupdf.Rect(x, 600 - v * 1.5, x + 70, 600), color=None, fill=(0.2, 0.4, 0.8))
            p.insert_text((x + 25, 620), q, fontsize=12)
            p.insert_text((x + 15, 590 - v * 1.5), f"{v}k EUR", fontsize=10)
        doc.save(path, garbage=4, deflate=True)


def sample2_pdf(path):
    with pymupdf.open() as doc:
        text_page(doc, A4, "Lighthouses", "The Port Vell lighthouse was built in 1904.")
        text_page(doc, A4, "Recipes", "A good paella needs bomba rice, saffron and a wide shallow pan.")
        text_page(doc, A4, "Astronomy", "Jupiter has at least 95 known moons; Ganymede is the largest.")
        doc.save(path, garbage=4, deflate=True)


def encrypted_pdf(path):
    with pymupdf.open() as doc:
        text_page(doc, A4, "Secret", "Nothing to see.")
        doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="owner-x")


def sample_docx(path):
    import docx
    from docx.enum.section import WD_SECTION
    from docx.shared import Inches
    d = docx.Document()
    d.add_heading("Project Kestrel", 0)
    d.add_paragraph("Project Kestrel kickoff is on 12 March 2027 in Lisbon.")
    t = d.add_table(rows=3, cols=2)
    t.style = "Table Grid"
    for r, (a, b) in enumerate((("Role", "Owner"), ("Lead", "Ana Duarte"), ("Budget", "85,000 EUR"))):
        t.cell(r, 0).text, t.cell(r, 1).text = a, b
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 60), False)
    pix.set_rect(pix.irect, (40, 120, 200))
    d.add_picture(io.BytesIO(pix.tobytes("png")), width=Inches(2))
    d.add_page_break()
    d.add_paragraph("Page two: the venue is the Lisbon Congress Centre.")
    d.add_section(WD_SECTION.CONTINUOUS)
    d.add_heading("Second section", 1)
    d.add_paragraph("Milestones: design review in May 2027, launch in October 2027.")
    d.save(path)


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    sample_pdf(out / "sample.pdf")
    sample2_pdf(out / "sample2.pdf")
    encrypted_pdf(out / "encrypted.pdf")
    (out / "not_a_pdf.pdf").write_bytes(random.Random(7).randbytes(2048))
    sample_docx(out / "sample.docx")
    for f in sorted(out.iterdir()):
        print(f.name, f.stat().st_size)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures")

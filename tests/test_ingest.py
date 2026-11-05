import dataclasses
import io
import threading
import time

import pytest

from app.backend import documents, store, worker
from app.backend.errors import Paused, RateLimited
from app.backend.rag import vectors
from tests.conftest import FIXTURES, FakeOpenRouter, make_pdf


def add(conn, cfg, path, name=None):
    with open(path, "rb") as f:
        return documents.add_file(conn, cfg, name or path.name, f)


def row(conn, doc_id):
    return dict(store.get(conn, doc_id))


def points(deps, doc_id=None):
    if not deps.qc.collection_exists("pages"):
        return []
    pts, _ = deps.qc.scroll("pages", limit=1000, with_payload=True)
    return sorted((p.payload["doc_id"], p.payload["page"]) for p in pts
                  if doc_id is None or p.payload["doc_id"] == doc_id)


# ---------------------------------------------------------------- adding

def test_add_pdf_and_dedup(deps, conn):
    doc_id, created = add(conn, deps.cfg, FIXTURES / "sample.pdf")
    assert (doc_id, created) == (1, True)
    assert (deps.cfg.data_dir / "docs/1/doc.pdf").read_bytes() == (FIXTURES / "sample.pdf").read_bytes()
    r = row(conn, 1)
    assert (r["kind"], r["title"], r["status"]) == ("pdf", "sample.pdf", "queued")
    assert r["dedup_key"].startswith("sha256:")
    # the same bytes under another name is a duplicate; the temp file is gone
    assert add(conn, deps.cfg, FIXTURES / "sample.pdf", "renamed.pdf") == (1, False)
    assert list((deps.cfg.data_dir / "tmp").iterdir()) == []


def test_add_rejects_other_types(deps, conn):
    with pytest.raises(documents.Rejected):
        documents.add_file(conn, deps.cfg, "notes.txt", io.BytesIO(b"hello"))
    assert store.list_docs(conn) == []


def test_add_rejects_too_large(deps, conn):
    cfg = dataclasses.replace(deps.cfg, max_upload_mb=1)
    with pytest.raises(documents.Rejected, match="larger than 1 MB"):
        documents.add_file(conn, cfg, "big.pdf", io.BytesIO(b"x" * (1024 * 1024 + 1)))
    assert list((cfg.data_dir / "tmp").iterdir()) == []


def test_add_url_dedup_and_normalize(conn):
    a = documents.add_url(conn, "  https://Example.com/a?x=1#frag \n")
    assert a == (1, True)
    assert row(conn, 1)["dedup_key"] == "url:https://example.com/a?x=1"
    assert documents.add_url(conn, "https://example.com/a?x=1") == (1, False)
    with pytest.raises(documents.Rejected):
        documents.add_url(conn, "ftp://example.com/file")


# ---------------------------------------------------------------- worker

def test_pdf_pipeline(deps, conn):
    add(conn, deps.cfg, FIXTURES / "sample.pdf")
    deps.cfg = dataclasses.replace(deps.cfg, embed_batch_pages=2)
    assert worker.run_one(deps, conn) == "done"
    r = row(conn, 1)
    assert (r["status"], r["page_count"], r["pages_embedded"]) == ("done", 3, 3)
    assert deps.embedder.page_calls == [2, 1]
    assert points(deps) == [(1, 1), (1, 2), (1, 3)]
    meta = deps.qc.get_collection("pages").config.metadata
    assert meta == {"embed_model": deps.cfg.embed_model, "dim": 8, "passage_mode": "field:document"}
    assert deps.qc.retrieve("pages", [10002])[0].payload == {"doc_id": 1, "page": 2}
    assert worker.run_one(deps, conn) == "idle"


def test_rate_limited_then_resume(deps, conn):
    deps.cfg = dataclasses.replace(deps.cfg, embed_batch_pages=8)
    add(conn, deps.cfg, make_pdf(deps.cfg.data_dir / "twelve.pdf", 12))
    deps.embedder.fail_on[2] = RateLimited(time.time() + 3600, "daily free quota reached")
    assert worker.run_one(deps, conn) == "waiting"
    r = row(conn, 1)
    assert (r["status"], r["pages_embedded"]) == ("queued", 8)
    assert r["next_attempt_at"] > time.time() and "4 of 12 pages pending" in r["message"]
    assert worker.run_one(deps, conn) == "idle"            # not claimable before next_attempt_at
    conn.execute("UPDATE documents SET next_attempt_at = 0")
    conn.commit()
    assert worker.run_one(deps, conn) == "done"
    assert deps.embedder.page_calls == [8, 4, 4]           # the failed call, then only pages 9-12 again
    assert len(points(deps)) == 12


def test_quota_budget_reserve(deps, conn):
    deps.cfg = dataclasses.replace(deps.cfg, embed_model="nvidia/nemotron-3.5-embed-8b:free",
                                   embed_batch_pages=1, or_reserve_requests=10)
    deps.openrouter = FakeOpenRouter(remaining=12)
    add(conn, deps.cfg, FIXTURES / "sample.pdf")
    assert worker.run_one(deps, conn) == "waiting"
    r = row(conn, 1)
    assert r["pages_embedded"] == 2 and "reserve" in r["message"]
    assert deps.embedder.page_calls == [1, 1]


def test_paused_leaves_document_queued(deps, conn):
    add(conn, deps.cfg, FIXTURES / "sample.pdf")
    deps.embedder.fail_on[1] = Paused("Qdrant is not running: make up")
    assert worker.run_one(deps, conn) == "paused"
    r = row(conn, 1)
    assert (r["status"], r["next_attempt_at"]) == ("queued", None)
    assert deps.status.paused == "Qdrant is not running: make up"
    assert worker.run_one(deps, conn) == "done"


def test_unexpected_exception_goes_to_error_and_loop_continues(deps, conn):
    add(conn, deps.cfg, FIXTURES / "sample.pdf")
    add(conn, deps.cfg, FIXTURES / "sample2.pdf")
    deps.embedder.fail_on[1] = KeyError("boom")
    stop = threading.Event()
    t = threading.Thread(target=worker.worker_loop, args=(deps, stop))
    t.start()
    for _ in range(100):
        if row(conn, 2)["status"] == "done":
            break
        time.sleep(0.05)
    stop.set()
    deps.wake.set()
    t.join(2)
    assert row(conn, 1)["status"] == "error" and row(conn, 1)["message"] == "KeyError: 'boom'"
    assert row(conn, 2)["status"] == "done"


def test_bad_pdf_goes_to_error(deps, conn):
    add(conn, deps.cfg, FIXTURES / "encrypted.pdf")
    assert worker.run_one(deps, conn) == "error"
    assert row(conn, 1)["message"] == "password-protected PDF"


# ---------------------------------------------------------------- recovery and startup check

def test_recover(deps, conn):
    add(conn, deps.cfg, FIXTURES / "sample.pdf")
    worker.run_one(deps, conn)
    add(conn, deps.cfg, FIXTURES / "sample2.pdf")
    conn.execute("UPDATE documents SET status = 'working' WHERE id = 2")
    conn.commit()
    conn.execute("DELETE FROM documents WHERE id = 1")      # a crash during delete: folder and points remain
    conn.commit()
    worker.recover(conn, deps.qc, deps.cfg)
    assert row(conn, 2)["status"] == "queued"
    assert not (deps.cfg.data_dir / "docs/1").exists()
    assert points(deps, 1) == []


def test_check_collection(deps, conn):
    vectors.check_collection(deps.qc, conn, deps.cfg)          # empty: fine
    add(conn, deps.cfg, FIXTURES / "sample.pdf")
    worker.run_one(deps, conn)
    vectors.check_collection(deps.qc, conn, deps.cfg)          # matching: fine
    other = dataclasses.replace(deps.cfg, embed_model="other/model:free")
    with pytest.raises(SystemExit, match="EMBED_MODEL changed from voyageai/voyage-multimodal-3.5 to "
                                         r"other/model:free: run 'make reembed' \(≈ 1 requests\)"):
        vectors.check_collection(deps.qc, conn, other)
    with pytest.raises(SystemExit, match="Passage mode changed"):
        vectors.check_collection(deps.qc, conn, dataclasses.replace(deps.cfg, embed_square_pages=True))
    deps.qc.delete_collection("pages")
    with pytest.raises(SystemExit, match="missing but 3 pages were embedded"):
        vectors.check_collection(deps.qc, conn, deps.cfg)


# ---------------------------------------------------------------- retry and delete

def test_delete_refused_while_working_then_cleans_up(deps, conn):
    add(conn, deps.cfg, FIXTURES / "sample.pdf")
    worker.run_one(deps, conn)
    conn.execute("UPDATE documents SET status = 'working'")
    conn.commit()
    assert documents.delete(deps, conn, 1) == "busy (being processed), try again in a moment"
    conn.execute("UPDATE documents SET status = 'done'")
    conn.commit()
    assert documents.delete(deps, conn, 1) is None
    assert store.get(conn, 1) is None and points(deps) == []
    assert not (deps.cfg.data_dir / "docs/1").exists()


def test_retry_compare_and_set(deps, conn):
    add(conn, deps.cfg, FIXTURES / "encrypted.pdf")
    assert documents.retry(deps, conn, 1) is not None            # queued, not waiting: refused
    worker.run_one(deps, conn)
    assert documents.retry(deps, conn, 1) is None
    r = row(conn, 1)
    assert (r["status"], r["message"]) == ("queued", None)


# ---------------------------------------------------------------- office and url via a fake Gotenberg

from email import policy
from email.parser import BytesParser

import httpx
import pymupdf

from app.backend.rag.convert import scroll_js
from tests.conftest import mock_http


def form_parts(request: httpx.Request) -> dict:
    """{name: (filename, value)} of a multipart request."""
    head = f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
    msg = BytesParser(policy=policy.default).parsebytes(head + request.content)
    return {p.get_param("name", header="content-disposition"): (p.get_filename(), p.get_content())
            for p in msg.iter_parts()}


def shot_jpeg(w=1120, h=2300) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    pix.clear_with(220)
    return pix.tobytes("jpeg")


class FakeWeb:
    """Gotenberg on 127.0.0.1:3100 plus the internet. Records every request."""

    def __init__(self, gotenberg_status=200, gotenberg_down=False, links=None, empty_unclipped=False):
        self.calls, self.status, self.down, self.links = [], gotenberg_status, gotenberg_down, links or {}
        self.empty_unclipped = empty_unclipped      # Chromium's answer for a page too tall for one capture

    def __call__(self, r: httpx.Request) -> httpx.Response:
        self.calls.append(r)
        if r.url.host == "127.0.0.1":
            if self.down:
                raise httpx.ConnectError("refused")
            if self.status != 200:
                return httpx.Response(self.status, text="Forbidden" if self.status == 403 else "boom")
            if r.url.path == "/forms/libreoffice/convert":
                return httpx.Response(200, content=(FIXTURES / "sample.pdf").read_bytes())
            if self.empty_unclipped and form_parts(r)["clip"][1] == "false":
                return httpx.Response(200, content=b"")
            return httpx.Response(200, content=shot_jpeg(), headers={"content-type": "image/jpeg"})
        if str(r.url) in self.links:
            ctype, body = self.links[str(r.url)]
            return httpx.Response(200, content=body, headers={"content-type": ctype})
        return httpx.Response(200, text="<html>hello</html>", headers={"content-type": "text/html"})

    def gotenberg_calls(self):
        return [c for c in self.calls if c.url.host == "127.0.0.1"]


def test_url_screenshot_pipeline(deps, conn):
    web = FakeWeb()
    deps.http = mock_http(web)
    documents.add_url(conn, "https://example.com/article")
    assert worker.run_one(deps, conn) == "done"
    (call,) = web.gotenberg_calls()
    assert call.url.path == "/forms/chromium/screenshot/url"
    parts = form_parts(call)
    assert {k: v for k, (_, v) in parts.items()} == {
        "url": "https://example.com/article", "width": "1120", "height": "1120", "clip": "false",
        "format": "jpeg", "quality": "85", "emulatedMediaType": "screen", "waitForExpression": scroll_js(deps.cfg)}
    assert all(filename is None for filename, _ in parts.values())     # form fields, not files
    r = row(conn, 1)
    assert (r["status"], r["page_count"], r["title"]) == ("done", 3, "https://example.com/article")
    assert (deps.cfg.data_dir / "docs/1/source.jpg").exists()
    assert points(deps) == [(1, 1), (1, 2), (1, 3)]


def test_office_pipeline(deps, conn):
    web = FakeWeb()
    deps.http = mock_http(web)
    add(conn, deps.cfg, FIXTURES / "sample.docx")
    assert (deps.cfg.data_dir / "docs/1/original.docx").exists()
    assert worker.run_one(deps, conn) == "done"
    (call,) = web.gotenberg_calls()
    assert call.url.path == "/forms/libreoffice/convert"
    parts = form_parts(call)
    assert list(parts) == ["files"] and parts["files"][0] == "original.docx"
    assert parts["files"][1] == (FIXTURES / "sample.docx").read_bytes()
    assert row(conn, 1)["page_count"] == 3                  # the fake answers with sample.pdf


def test_pdf_link_skips_gotenberg(deps, conn):
    url = "https://arxiv.org/pdf/1706.03762"
    web = FakeWeb(links={url: ("application/pdf", (FIXTURES / "sample.pdf").read_bytes())})
    deps.http = mock_http(web)
    documents.add_url(conn, url)
    assert worker.run_one(deps, conn) == "done"
    assert web.gotenberg_calls() == []
    assert (deps.cfg.data_dir / "docs/1/doc.pdf").read_bytes() == (FIXTURES / "sample.pdf").read_bytes()
    assert row(conn, 1)["page_count"] == 3


def test_docx_link_goes_to_libreoffice(deps, conn):
    url = "https://example.com/files/plan"
    web = FakeWeb(links={url: (DOCX, (FIXTURES / "sample.docx").read_bytes())})
    deps.http = mock_http(web)
    documents.add_url(conn, url)
    assert worker.run_one(deps, conn) == "done"
    assert [c.url.path for c in web.gotenberg_calls()] == ["/forms/libreoffice/convert"]


DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_gotenberg_403_is_error_with_hint(deps, conn):
    deps.http = mock_http(FakeWeb(gotenberg_status=403))
    documents.add_url(conn, "https://nonexistent.invalid")
    assert worker.run_one(deps, conn) == "error"
    assert row(conn, 1)["message"].startswith("URL blocked or host not resolvable")


def test_gotenberg_down_pauses_and_keeps_queued(deps, conn):
    deps.http = mock_http(FakeWeb(gotenberg_down=True))
    documents.add_url(conn, "https://example.com")
    assert worker.run_one(deps, conn) == "paused"
    r = row(conn, 1)
    assert (r["status"], r["next_attempt_at"]) == ("queued", None)
    assert deps.status.paused == "Gotenberg is not running: make up"
    deps.http = mock_http(FakeWeb())
    assert worker.run_one(deps, conn) == "done"


def test_no_quota_budget_for_paid_models(deps, conn):
    deps.cfg = dataclasses.replace(deps.cfg, embed_batch_pages=1)       # default embedder is paid
    deps.openrouter = FakeOpenRouter(remaining=0)
    add(conn, deps.cfg, FIXTURES / "sample.pdf")
    assert worker.run_one(deps, conn) == "done"


def test_reembed(deps, conn, capsys):
    add(conn, deps.cfg, FIXTURES / "sample.pdf")
    worker.run_one(deps, conn)
    assert worker.reembed(deps.cfg, deps.qc, confirm=lambda p: "n") == 1        # 'n' changes nothing
    assert deps.qc.collection_exists("pages") and row(conn, 1)["status"] == "done"
    held = worker.take_lock(deps.cfg)
    assert worker.reembed(deps.cfg, deps.qc, confirm=lambda p: "y") == 1        # the app holds the lock
    assert "stop the web app first" in capsys.readouterr().out
    held.close()
    prompts = []
    assert worker.reembed(deps.cfg, deps.qc, confirm=lambda p: (prompts.append(p), "y")[1]) == 0
    assert "about 1 requests" in prompts[0]
    assert not deps.qc.collection_exists("pages")
    r = row(conn, 1)
    assert (r["status"], r["pages_embedded"]) == ("queued", 0)
    assert worker.run_one(deps, conn) == "done" and len(points(deps)) == 3      # re-embedded from the JPEGs


def test_scroll_reaches_as_far_as_the_pages_kept(deps):
    assert "n < 200;" in scroll_js(deps.cfg)
    assert "n < 28;" in scroll_js(dataclasses.replace(deps.cfg, max_web_pages=7))


def test_scroll_ignores_smooth_scrolling(deps):
    assert scroll_js(deps.cfg).count("behavior: 'instant'") == 2


def test_too_tall_page_falls_back_to_clipped_capture(deps, conn):
    web = FakeWeb(empty_unclipped=True)
    deps.http = mock_http(web)
    documents.add_url(conn, "https://en.wikipedia.org/wiki/History_of_the_United_States")
    assert worker.run_one(deps, conn) == "done"
    first, second = web.gotenberg_calls()
    assert form_parts(first)["clip"][1] == "false"
    assert (form_parts(second)["clip"][1], form_parts(second)["height"][1]) == ("true", str(50 * 1120))
    assert row(conn, 1)["warning"] == "page too tall to capture in one shot; only the first 50 pages are kept"


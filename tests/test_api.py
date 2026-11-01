"""JSON API under /api (PLAN.md §7). The app runs without its lifespan; deps come from conftest."""
import dataclasses
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend import store
from app.backend.errors import Paused
from app.backend.main import app
from tests.conftest import FIXTURES, FakeOpenRouter
from tests.test_query import library, query_matching


class Worker:
    def __init__(self, alive=True):
        self.alive = alive

    def is_alive(self):
        return self.alive


@pytest.fixture
def client(deps):
    app.state.deps, app.state.worker = deps, Worker()
    return TestClient(app)


def set_row(conn, doc_id, **cols):
    conn.execute(f"UPDATE documents SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?", [*cols.values(), doc_id])
    conn.commit()


# ---------------------------------------------------------------- library and banner

def test_empty_library_does_not_poll(client):
    assert client.get("/api/library").json() == {"docs": [], "banner": None, "poll_ms": None}


def test_library_poll_interval(client, deps, conn):
    library(deps, conn, "sample.pdf")
    client.post("/api/add", data={"urls": "https://example.com/a\nhttps://example.com/b"})
    lib = client.get("/api/library").json()
    assert [(d["id"], d["status"]) for d in lib["docs"]] == [(3, "queued"), (2, "queued"), (1, "done")]
    assert lib["docs"][2]["pages_embedded"] == 3 and lib["poll_ms"] == 2000
    assert [d["file_url"] for d in lib["docs"]] == [None, None, "/files/1/doc.pdf"]
    set_row(conn, 2, next_attempt_at=time.time() + 3600, message="daily free quota reached; resumes 01:01")
    set_row(conn, 3, status="error", message="boom")
    lib = client.get("/api/library").json()
    assert [d["waiting"] for d in lib["docs"]] == [False, True, False] and lib["poll_ms"] == 30000
    set_row(conn, 2, status="working")
    assert client.get("/api/library").json()["poll_ms"] == 2000
    set_row(conn, 2, status="done")
    assert client.get("/api/library").json()["poll_ms"] is None


def test_banner(client, deps):
    deps.status.paused, deps.status.until = "Gotenberg is not running (make up)", None
    assert client.get("/api/library").json()["banner"] == "Worker paused: Gotenberg is not running (make up); retrying "
    app.state.worker = Worker(alive=False)
    assert client.get("/api/library").json()["banner"] == "Worker stopped; see the log and restart"


def test_quota_only_for_free_models(client, deps):
    assert client.get("/api/quota").json() == {"quota": None}
    deps.cfg = dataclasses.replace(deps.cfg, answer_model="nvidia/nemotron-3.5-super-vl:free")
    deps.openrouter = FakeOpenRouter(remaining=40)
    assert client.get("/api/quota").json()["quota"].startswith("Free requests today: 10/50 used (resets ")


# ---------------------------------------------------------------- add

def test_add_files_and_links(client, deps, conn):
    with open(FIXTURES / "sample.pdf", "rb") as f:
        pdf = f.read()
    files = [("files", ("sample.pdf", pdf, "application/pdf")), ("files", ("notes.txt", b"hi", "text/plain"))]
    r = client.post("/api/add", files=files, data={"urls": "https://Example.com/x\n\n  ftp://example.com/y \n"})
    assert r.json() == {"added": 2, "duplicates": [], "rejected": [
        "notes.txt: only .pdf and .docx files", "ftp://example.com/y: not an http(s) link"]}
    assert deps.wake.is_set()
    deps.wake.clear()
    r = client.post("/api/add", files=files[:1], data={"urls": "https://example.com/x"})
    assert r.json()["added"] == 0 and not deps.wake.is_set()
    assert r.json()["duplicates"] == [{"id": 1, "title": "sample.pdf", "status": "queued"},
                                      {"id": 2, "title": "https://example.com/x", "status": "queued"}]


def test_add_nothing(client):
    assert client.post("/api/add", data={"urls": ""}).json() == {"added": 0, "duplicates": [], "rejected": []}


# ---------------------------------------------------------------- search and ask

def test_search_messages(client, deps):
    assert client.get("/api/search", params={"q": "  "}).json() == {"groups": [], "message": "Type a question first."}
    assert client.get("/api/search", params={"q": "total"}).json() == {"groups": [], "message": "No documents yet."}
    assert deps.embedder.query_calls == []


def test_search_groups(client, deps, conn):
    library(deps, conn, "sample.pdf", "sample2.pdf")
    query_matching(deps, 1, 2)
    body = client.get("/api/search", params={"q": "invoice total"}).json()
    assert body["message"] is None and [len(g) for g in body["groups"]] == [3, 3]
    top = body["groups"][0][0]
    assert top["image_url"] == "/files/1/pages/0002.jpg" and top["file_url"] == "/files/1/doc.pdf"
    assert (top["doc_id"], top["page_no"], top["title"], top["kind"]) == (1, 2, "sample.pdf", "pdf")
    assert top["score"] == pytest.approx(1.0)


def test_search_no_matching_pages(client, deps, conn):
    library(deps, conn, "sample.pdf")
    deps.qc.delete("pages", points_selector=[10001, 10002, 10003])
    assert client.get("/api/search", params={"q": "total"}).json() == {"groups": [], "message": "No matching pages."}


def test_ask(client, deps, conn):
    library(deps, conn, "sample.pdf", "sample2.pdf")
    query_matching(deps, 1, 2)
    body = client.post("/api/ask", json={"q": "What is the invoice total?"}).json()
    assert body["message"] is None
    assert body["answer"]["text"] == "The total is 4,312 EUR [S1]." and body["answer"]["model"] == deps.cfg.answer_model
    assert next(s["image_url"] for s in body["answer"]["sources"]) == "/files/1/pages/0002.jpg"
    assert len(body["answer"]["sources"]) == 6
    assert [len(g) for g in body["groups"]] == [3, 3] and body["groups"][0][0]["image_url"] == "/files/1/pages/0002.jpg"


def test_ask_messages(client, deps, conn):
    assert client.post("/api/ask", json={}).json() == {"answer": None, "groups": [], "message": "Type a question first."}
    library(deps, conn, "sample.pdf")
    deps.openrouter.error = Paused("OpenRouter error: provider died")
    assert client.post("/api/ask", json={"q": "total"}).json() == {"answer": None, "groups": [],
                                                                    "message": "OpenRouter error: provider died"}


def test_qdrant_down(client, deps):
    class Down:
        def collection_exists(self, name):
            raise httpx.ConnectError("refused")

        def close(self):
            pass
    deps.qc = Down()
    assert client.get("/api/search", params={"q": "total"}).json()["message"] == "Qdrant is not running: make up"
    assert client.post("/api/ask", json={"q": "total"}).json()["message"] == "Qdrant is not running: make up"


# ---------------------------------------------------------------- retry and delete

def test_retry(client, deps, conn):
    library(deps, conn, "sample.pdf")
    assert client.post("/api/docs/1/retry").json() == {"message": "only failed or waiting documents can be retried"}
    set_row(conn, 1, status="error", message="boom")
    deps.wake.clear()
    assert client.post("/api/docs/1/retry").json() == {"message": None}
    assert store.get(conn, 1)["status"] == "queued" and deps.wake.is_set()


def test_delete(client, deps, conn):
    library(deps, conn, "sample.pdf")
    set_row(conn, 1, status="working")
    assert client.delete("/api/docs/1").json() == {"message": "busy (being processed), try again in a moment"}
    set_row(conn, 1, status="done")
    assert client.delete("/api/docs/1").json() == {"message": None}
    assert store.get(conn, 1) is None and not store.doc_dir(deps.cfg, 1).exists()
    assert deps.qc.count("pages").count == 0
    assert client.delete("/api/docs/1").json() == {"message": None}          # already gone: nothing to report


# ---------------------------------------------------------------- web UI files

def test_spa_fallback(tmp_path):
    """Page loads of client routes get index.html; fetch() calls and scripts that miss get a 404."""
    (tmp_path / "index.html").write_text("app")
    (tmp_path / "app.js").write_text("js")
    web = FastAPI()
    web.frontend("/", directory=tmp_path)
    c = TestClient(web)
    page = {"accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
    assert c.get("/").text == c.get("/library", headers=page).text == c.get("/docs/3", headers=page).text == "app"
    assert c.get("/app.js").text == "js"
    assert c.get("/missing.js").status_code == c.get("/api/nope").status_code == 404


# ---------------------------------------------------------------- config

def test_config_shows_models_but_not_the_key(client, deps):
    cfg = client.get("/api/config").json()
    assert cfg["answer"]["model"] == deps.cfg.answer_model
    assert cfg["answer"]["temperature"] == deps.cfg.answer_temperature
    assert cfg["embedding"]["model"] == deps.cfg.embed_model
    assert deps.cfg.openrouter_api_key not in str(cfg)

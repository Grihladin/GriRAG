import base64
import dataclasses

import httpx
import pymupdf
import pytest

from app import DocError, Paused, RateLimited
from app.embedder import OpenRouterEmbedder
from app.main import SYSTEM_PROMPT, build_messages
from app.openrouter import OpenRouter, next_utc_midnight
from tests.conftest import body_of, key_response, mock_http


def jpeg(w, h):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    pix.clear_with(0)
    return pix.tobytes("jpeg")


def vec_response(n, dim=4, index=True, reverse=False):
    data = [{"embedding": [float(i + 1)] * dim, **({"index": i} if index else {})} for i in range(n)]
    return httpx.Response(200, json={"data": data[::-1] if reverse else data})


def make(cfg, clock, handler):
    orr = OpenRouter(cfg, mock_http(handler), clock=clock, sleep=clock.sleep)
    return orr, OpenRouterEmbedder(cfg, orr)


# ---------------------------------------------------------------- embedder request bodies

def test_field_mode_bodies(cfg, clock):
    cfg = dataclasses.replace(cfg, embed_square_pages=True, embed_passage_type="passage")
    seen = []
    _, emb = make(cfg, clock, lambda r: (seen.append(body_of(r)), vec_response(len(body_of(r)["input"])
                                                                              if isinstance(body_of(r)["input"], list) else 1))[1])
    emb.embed_pages([jpeg(1187, 1536), jpeg(1120, 1120)])
    emb.embed_query("what?")
    pages, query = seen
    assert pages["input_type"] == "passage" and pages["encoding_format"] == "float"
    assert pages["model"] == cfg.embed_model
    assert len(pages["input"]) == 2
    part = pages["input"][0]["content"][0]
    assert part["type"] == "image_url" and part["image_url"]["url"].startswith("data:image/jpeg;base64,")
    sent = pymupdf.Pixmap(base64.b64decode(part["image_url"]["url"].split(",", 1)[1]))
    assert (sent.width, sent.height) == (1536, 1536)        # padded to a square for the embedder
    assert query == {"model": cfg.embed_model, "input": "what?", "input_type": "query", "encoding_format": "float"}


def test_prefix_mode_bodies(cfg, clock):
    cfg = dataclasses.replace(cfg, embed_input_mode="prefix")
    seen = []
    _, emb = make(cfg, clock, lambda r: (seen.append(body_of(r)), vec_response(1))[1])
    emb.embed_pages([jpeg(10, 10)])
    emb.embed_query("what?")
    pages, query = seen
    assert "input_type" not in pages and "input_type" not in query
    assert pages["input"][0]["content"][0] == {"type": "text", "text": "passage:"}
    assert query["input"] == "query: what?"
    assert emb.passage_mode == "prefix"


def test_results_reordered_by_index(cfg, clock):
    _, emb = make(cfg, clock, lambda r: vec_response(3, reverse=True))
    assert [v[0] for v in emb.embed_pages([jpeg(10, 10)] * 3)] == [1.0, 2.0, 3.0]


def test_results_kept_in_list_order_without_index(cfg, clock):
    _, emb = make(cfg, clock, lambda r: vec_response(3, index=False, reverse=True))
    assert [v[0] for v in emb.embed_pages([jpeg(10, 10)] * 3)] == [3.0, 2.0, 1.0]


def test_wrong_count_is_doc_error(cfg, clock):
    _, emb = make(cfg, clock, lambda r: vec_response(1))
    with pytest.raises(DocError, match="wrong count"):
        emb.embed_pages([jpeg(10, 10)] * 2)


# ---------------------------------------------------------------- throttle and errors

def test_throttle_slots(cfg, clock):
    orr, _ = make(cfg, clock, lambda r: httpx.Response(200, json={"ok": 1}))
    for _ in range(3):
        orr.post("/x", {})
    assert clock.sleeps == [pytest.approx(3.2), pytest.approx(3.2)]


def test_429_daily(cfg, clock):
    def h(r):
        if r.url.path.endswith("/key"):
            return key_response(remaining=0, used=50)
        return httpx.Response(429, json={"error": {"code": 429, "message": "Rate limit exceeded"}})
    orr, _ = make(cfg, clock, h)
    with pytest.raises(RateLimited) as e:
        orr.post("/embeddings", {"input": []})
    assert e.value.retry_at == next_utc_midnight(clock.t) + 60
    assert "daily" in e.value.reason


def test_429_retry_after_and_backoff(cfg, clock):
    def h(r):
        if r.url.path.endswith("/key"):
            return key_response(remaining=30)
        return httpx.Response(429, headers={"Retry-After": "7"}, json={"error": {"message": "slow down"}})
    orr, _ = make(cfg, clock, h)
    waits = []
    for _ in range(3):
        with pytest.raises(RateLimited) as e:
            orr.post("/embeddings", {"input": []})
        waits.append(round(e.value.retry_at - clock.t))
    assert waits == [60, 120, 240]


def test_backoff_resets_after_success(cfg, clock):
    state = {"fail": True}
    def h(r):
        if r.url.path.endswith("/key"):
            return key_response(remaining=30)
        return httpx.Response(429, json={}) if state["fail"] else httpx.Response(200, json={"ok": 1})
    orr, _ = make(cfg, clock, h)
    for _ in range(2):
        with pytest.raises(RateLimited):
            orr.post("/x", {})
    state["fail"] = False
    orr.post("/x", {})
    state["fail"] = True
    with pytest.raises(RateLimited) as e:
        orr.post("/x", {})
    assert round(e.value.retry_at - clock.t) == 60


@pytest.mark.parametrize("status,exc,text", [
    (400, DocError, "EMBED_BATCH_PAGES"), (413, DocError, "EMBED_BATCH_PAGES"), (401, Paused, "API_KEY"),
    (402, Paused, "credits"), (404, Paused, "settings/privacy"), (403, DocError, "moderation"),
    (502, Paused, "502"), (503, Paused, "503"), (408, Paused, "408")])
def test_error_mapping(cfg, clock, status, exc, text):
    orr, _ = make(cfg, clock, lambda r: httpx.Response(status, json={"error": {"message": "boom"}}))
    with pytest.raises(exc, match=text):
        orr.post("/embeddings", {"input": []})


def test_network_error_pauses(cfg, clock):
    def h(r):
        raise httpx.ConnectError("refused")
    orr, _ = make(cfg, clock, h)
    with pytest.raises(Paused, match="unreachable"):
        orr.post("/x", {})


def test_error_inside_200(cfg, clock):
    orr, _ = make(cfg, clock, lambda r: httpx.Response(200, json={"error": {"message": "provider died"}}))
    with pytest.raises(Paused, match="provider died"):
        orr.chat("m", [], max_tokens=10)


def test_empty_content_with_length(cfg, clock):
    resp = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}], "model": "m"}
    orr, _ = make(cfg, clock, lambda r: httpx.Response(200, json=resp))
    with pytest.raises(DocError, match="ANSWER_MAX_TOKENS"):
        orr.chat("m", [], max_tokens=10)


def test_free_quota(cfg, clock):
    calls = []
    orr, _ = make(cfg, clock, lambda r: (calls.append(1), key_response(remaining=12, used=38))[1])
    assert orr.free_quota() == {"used": 38, "limit": 50, "remaining": 12}
    orr.free_quota()
    assert len(calls) == 1                     # cached for 60 s


# ---------------------------------------------------------------- answer messages

def test_build_messages_order():
    msgs = build_messages("What is the total?", [("[S1] a.pdf, page 2", b"A"), ("[S2] b.docx, page 1", b"B")])
    assert msgs[0] == {"role": "system", "content": SYSTEM_PROMPT}
    parts = msgs[1]["content"]
    assert [p["type"] for p in parts] == ["text", "text", "image_url", "text", "image_url"]
    assert parts[0]["text"] == "Question: What is the total?"
    assert parts[1]["text"] == "[S1] a.pdf, page 2" and parts[3]["text"] == "[S2] b.docx, page 1"
    assert parts[2]["image_url"]["url"] == "data:image/jpeg;base64,QQ=="


def test_502_is_retried(cfg, clock):
    replies = [502, 502, 200]
    calls = []
    def h(r):
        calls.append(1)
        s = replies.pop(0)
        return httpx.Response(s, json={"ok": 1} if s == 200 else {"error": {"message": "service inference failed"}})
    orr, _ = make(cfg, clock, h)
    assert orr.post("/embeddings", {"input": []}) == {"ok": 1}
    assert len(calls) == 3 and clock.sleeps == [pytest.approx(3.2)] * 2     # each retry waits for its slot


def test_502_gives_up_after_four_attempts(cfg, clock):
    calls = []
    orr, _ = make(cfg, clock, lambda r: (calls.append(1), httpx.Response(502, json={"error": {"message": "x"}}))[1])
    with pytest.raises(Paused, match="502"):
        orr.post("/embeddings", {"input": []})
    assert len(calls) == 4


def test_pages_sent_unpadded_by_default(cfg, clock):
    seen = []
    _, emb = make(cfg, clock, lambda r: (seen.append(body_of(r)), vec_response(1))[1])
    emb.embed_pages([jpeg(1187, 1536)])
    url = seen[0]["input"][0]["content"][0]["image_url"]["url"]
    sent = pymupdf.Pixmap(base64.b64decode(url.split(",", 1)[1]))
    assert (sent.width, sent.height) == (1187, 1536)
    assert seen[0]["input_type"] == "document" and emb.passage_mode == "field:document"
    assert dataclasses.replace(cfg, embed_square_pages=True).passage_mode == "field:document+square"


# ---------------------------------------------------------------- search and ask

from app import ingest, store
from app.main import Answer, ask, search
from tests.conftest import FIXTURES, FakeEmbedder, FakeOpenRouter


def library(deps, conn, *names):
    """Add and embed fixture PDFs; returns nothing. Page vectors come from FakeEmbedder (hash of the bytes)."""
    for name in names:
        with open(FIXTURES / name, "rb") as f:
            ingest.add_file(conn, deps.cfg, name, f)
        assert ingest.run_one(deps, conn) == "done"


def query_matching(deps, doc_id, page):
    """Make the next query vector equal a stored page vector, so that page ranks first."""
    jpeg = store.page_path(deps.cfg, doc_id, page).read_bytes()
    deps.embed_query = lambda q: FakeEmbedder.vector(jpeg)


def test_blank_question_makes_no_request(deps, conn):
    assert search(deps, conn, "   ") == "Type a question first."
    assert ask(deps, conn, "") == "Type a question first."
    assert deps.embedder.query_calls == [] and deps.openrouter.chats == []


def test_empty_library_makes_no_request(deps, conn):
    assert search(deps, conn, "invoice total") == "No documents yet."
    assert ask(deps, conn, "invoice total") == "No documents yet."
    assert deps.embedder.query_calls == []


def test_zero_hits_makes_no_chat_request(deps, conn):
    library(deps, conn, "sample.pdf")
    deps.qc.delete("pages", points_selector=[10001, 10002, 10003])      # collection exists but is empty
    assert ask(deps, conn, "invoice total") == "No matching pages."
    assert deps.openrouter.chats == []


def test_search_groups_by_document(deps, conn):
    library(deps, conn, "sample.pdf", "sample2.pdf")
    query_matching(deps, 1, 2)
    groups = search(deps, conn, "invoice total")
    assert [g[0].doc_id for g in groups][0] == 1
    assert groups[0][0].page_no == 2 and groups[0][0].score == pytest.approx(1.0)
    assert {len(g) for g in groups} == {3}
    assert groups[0][0].image_url == "/files/1/pages/0002.jpg" and groups[0][0].file_url == "/files/1/doc.pdf"


def test_search_drops_hits_without_a_row(deps, conn):
    library(deps, conn, "sample.pdf", "sample2.pdf")
    conn.execute("DELETE FROM documents WHERE id = 1")
    conn.commit()
    assert [g[0].doc_id for g in search(deps, conn, "anything")] == [2]


def test_query_embedding_is_cached(deps, conn):
    library(deps, conn, "sample.pdf")
    search(deps, conn, "invoice total")
    search(deps, conn, "invoice total ")
    ask(deps, conn, "invoice total")
    assert deps.embedder.query_calls == ["invoice total"]


def test_ask_sends_three_best_pages_with_labels(deps, conn):
    library(deps, conn, "sample.pdf", "sample2.pdf")
    query_matching(deps, 1, 2)
    deps.openrouter.reply = "<think>let me look</think>\nThe total is 4,312 EUR [S1]."
    result = ask(deps, conn, " What is the invoice total? ")
    assert isinstance(result, Answer)
    assert result.text == "The total is 4,312 EUR [S1]." and result.model == deps.cfg.answer_model
    assert deps.openrouter.reasoning_effort == deps.cfg.answer_reasoning_effort
    assert deps.openrouter.temperature == deps.cfg.answer_temperature
    assert len(result.sources) == 3 and (result.sources[0].doc_id, result.sources[0].page_no) == (1, 2)
    assert [s.score for s in result.sources] == sorted((s.score for s in result.sources), reverse=True)
    parts = deps.openrouter.chats[0][1]["content"]
    assert parts[0]["text"] == "Question: What is the invoice total?"
    assert parts[1]["text"] == "[S1] sample.pdf, page 2"
    assert [p["type"] for p in parts] == ["text"] + ["text", "image_url"] * 3


@pytest.mark.parametrize("error,message", [
    (DocError("The model used its whole token budget on reasoning; raise ANSWER_MAX_TOKENS in .env."),
     "raise ANSWER_MAX_TOKENS"),
    (Paused("OpenRouter error: provider died"), "provider died"),
    (RateLimited(0, "daily free quota reached"), "Daily free limit reached"),
    (RateLimited(9e9, "rate-limited (slow down); retrying in 60 s"), "Rate-limited, try again in")])
def test_ask_errors_become_messages(deps, conn, error, message):
    library(deps, conn, "sample.pdf")
    deps.openrouter.error = error
    assert message in ask(deps, conn, "invoice total")


def test_qdrant_down_message(deps, conn):
    class Down:
        def collection_exists(self, name):
            raise httpx.ConnectError("refused")

        def close(self):
            pass
    deps.qc = Down()
    assert search(deps, conn, "invoice total") == "Qdrant is not running: make up"

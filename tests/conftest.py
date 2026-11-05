import json

import httpx
import pytest

from app.backend.config import Config


@pytest.fixture
def cfg(tmp_path):
    return Config(openrouter_api_key="sk-or-test", data_dir=tmp_path / "data", or_min_interval_s=3.2)


class FakeClock:
    def __init__(self, t=1_000_000.0):
        self.t = t
        self.sleeps = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


@pytest.fixture
def clock():
    return FakeClock()


def mock_http(handler):
    """httpx.Client whose requests go to handler(request) -> httpx.Response."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def body_of(request: httpx.Request) -> dict:
    return json.loads(request.content)


def key_response(remaining=40, used=10, limit=50):
    return httpx.Response(200, json={"data": {"free_model_daily_requests":
                                              {"used": used, "limit": limit, "remaining": remaining}}})


# ---------------------------------------------------------------- ingest fixtures

import hashlib
from pathlib import Path

from qdrant_client import QdrantClient

from app.backend import store
from app.backend.deps import Deps

FIXTURES = Path(__file__).parent / "fixtures"


class FakeEmbedder:
    """Deterministic vectors from a hash of the bytes; counts calls; can fail on a given call."""
    model_id = "voyageai/voyage-multimodal-3.5"
    passage_mode = "field:document"

    def __init__(self, dim=8):
        self.dim, self.page_calls, self.query_calls = dim, [], []
        self.fail_on = {}                          # call number (1-based) -> exception

    @staticmethod
    def vector(data: bytes, dim=8) -> list[float]:
        h = hashlib.sha256(data).digest()
        return [b / 255 + 0.01 for b in h[:dim]]

    def embed_pages(self, jpegs):
        self.page_calls.append(len(jpegs))
        if exc := self.fail_on.pop(len(self.page_calls), None):
            raise exc
        return [self.vector(j, self.dim) for j in jpegs]

    def embed_query(self, text):
        self.query_calls.append(text)
        return self.vector(text.encode(), self.dim)


class FakeOpenRouter:
    def __init__(self, remaining=None, reply="The total is 4,312 EUR [S1].", error=None):
        self.remaining, self.reply, self.error, self.chats = remaining, reply, error, []

    def chat(self, model, messages, *, max_tokens, reasoning_effort=None, temperature=0.4):
        self.chats.append(messages)
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.temperature = temperature
        if self.error:
            raise self.error
        return self.reply, model

    def free_quota(self, cached=True):
        return None if self.remaining is None else {"used": 50 - self.remaining, "limit": 50,
                                                     "remaining": self.remaining}


@pytest.fixture
def deps(cfg):
    for sub in ("docs", "tmp"):
        (cfg.data_dir / sub).mkdir(parents=True, exist_ok=True)
    d = Deps(cfg=cfg, connect=lambda: store.connect(cfg), qc=QdrantClient(":memory:"),
             openrouter=FakeOpenRouter(), embedder=FakeEmbedder(),
             http=mock_http(lambda r: httpx.Response(599, text="no network in tests")))
    yield d
    d.qc.close()


@pytest.fixture
def conn(deps):
    c = deps.connect()
    yield c
    c.close()


def make_pdf(path: Path, pages: int, size=(595, 842)) -> Path:
    import pymupdf
    with pymupdf.open() as doc:
        for i in range(pages):
            doc.new_page(width=size[0], height=size[1]).insert_text((60, 90), f"page {i + 1}", fontsize=20)
        doc.save(path)
    return path

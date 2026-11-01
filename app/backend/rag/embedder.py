"""Embedder interface (the swap seam for a local embedder later) and the OpenRouter implementation."""
from typing import Protocol

from app.backend.config import Config
from app.backend.errors import DocError
from app.backend.rag.openrouter import OpenRouter, image_part
from app.backend.rag.render import square_jpeg


class Embedder(Protocol):
    model_id: str
    passage_mode: str                                                     # stored on the collection
    def embed_pages(self, jpegs: list[bytes]) -> list[list[float]]: ...   # documents (passage mode)
    def embed_query(self, text: str) -> list[float]: ...                  # questions (query mode)


def parse_vectors(body: dict, n: int) -> list[list[float]]:
    """The n vectors of an /embeddings response, in input order."""
    data = body.get("data") or []
    if all("index" in d for d in data):
        data = sorted(data, key=lambda d: d["index"])
    vecs = [d.get("embedding") for d in data]
    if len(vecs) != n or not all(isinstance(v, list) and v for v in vecs) or len({len(v) for v in vecs}) != 1:
        raise DocError("embedder returned a wrong count or length")
    return vecs


class OpenRouterEmbedder:
    """Pages in passage mode, questions in query mode; EMBED_INPUT_MODE picks input_type (field) or text prefixes."""

    def __init__(self, cfg: Config, openrouter: OpenRouter):
        self.cfg, self.openrouter = cfg, openrouter
        self.model_id = cfg.embed_model
        self.passage_mode = cfg.passage_mode

    def request_body(self, inputs, input_type: str) -> dict:
        body = {"model": self.model_id, "input": inputs, "encoding_format": "float"}
        if self.cfg.embed_input_mode == "field":
            body["input_type"] = input_type
        return body

    def page_inputs(self, jpegs: list[bytes]) -> list[dict]:
        prefix = [{"type": "text", "text": "passage:"}] if self.cfg.embed_input_mode == "prefix" else []
        return [{"content": prefix + [image_part(j)]} for j in jpegs]

    def query_input(self, text: str) -> str:
        return f"query: {text}" if self.cfg.embed_input_mode == "prefix" else text

    def embed_pages(self, jpegs: list[bytes]) -> list[list[float]]:
        if self.cfg.embed_square_pages:
            jpegs = [square_jpeg(j, self.cfg.jpeg_quality) for j in jpegs]
        body = self.openrouter.post("/embeddings", self.request_body(self.page_inputs(jpegs), self.cfg.embed_passage_type))
        return parse_vectors(body, len(jpegs))

    def embed_query(self, text: str) -> list[float]:
        body = self.openrouter.post("/embeddings", self.request_body(self.query_input(text), self.cfg.embed_query_type))
        return parse_vectors(body, 1)[0]

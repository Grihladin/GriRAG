"""Embedder interface (the swap seam for a local embedder later) and the OpenRouter implementation."""
import base64
from typing import Protocol

from app import DocError
from app.convert import square_jpeg
from app.config import Config
from app.openrouter import OpenRouter


class Embedder(Protocol):
    model_id: str
    passage_mode: str                                                     # stored on the collection
    def embed_pages(self, jpegs: list[bytes]) -> list[list[float]]: ...   # documents (passage mode)
    def embed_query(self, text: str) -> list[float]: ...                  # questions (query mode)


def data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


def image_part(jpeg: bytes) -> dict:
    return {"type": "image_url", "image_url": {"url": data_url(jpeg)}}


def parse_vectors(body: dict, n: int) -> list[list[float]]:
    data = body.get("data") or []
    if all("index" in d for d in data):
        data = sorted(data, key=lambda d: d["index"])
    vecs = [d.get("embedding") for d in data]
    if len(vecs) != n or not all(isinstance(v, list) and v for v in vecs) or len({len(v) for v in vecs}) != 1:
        raise DocError("embedder returned a wrong count or length")
    return vecs


class OpenRouterEmbedder:
    def __init__(self, cfg: Config, openrouter: OpenRouter):
        self.cfg, self.openrouter = cfg, openrouter
        self.model_id = cfg.embed_model
        self.passage_mode = cfg.passage_mode

    def _body(self, inputs, input_type: str) -> dict:
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
        body = self.openrouter.post("/embeddings", self._body(self.page_inputs(jpegs), self.cfg.embed_passage_type))
        return parse_vectors(body, len(jpegs))

    def embed_query(self, text: str) -> list[float]:
        body = self.openrouter.post("/embeddings", self._body(self.query_input(text), self.cfg.embed_query_type))
        return parse_vectors(body, 1)[0]

"""Everything the routes and the worker share, in one object so tests can inject fakes."""
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

import httpx
from qdrant_client import QdrantClient

from app.backend.config import Config
from app.backend.rag.embedder import Embedder
from app.backend.rag.openrouter import OpenRouter


@dataclass
class WorkerStatus:
    paused: str | None = None        # banner text while the worker pauses
    until: float | None = None       # when it tries again


@dataclass
class Deps:
    cfg: Config
    connect: Callable[[], sqlite3.Connection]
    qc: QdrantClient
    openrouter: OpenRouter
    embedder: Embedder
    http: httpx.Client                                # Gotenberg and link downloads
    wake: threading.Event = field(default_factory=threading.Event)
    status: WorkerStatus = field(default_factory=WorkerStatus)
    embed_query: Callable[[str], list[float]] = field(init=False)   # embedder.embed_query, cached

    def __post_init__(self):
        self.embed_query = lru_cache(256)(self.embedder.embed_query)

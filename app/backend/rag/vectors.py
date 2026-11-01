"""Page vectors in Qdrant: one point per page, grouped search per document. PLAN.md §4.2."""
import warnings
from contextlib import contextmanager

import httpx
from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.backend import store
from app.backend.config import Config
from app.backend.errors import DocError, Paused


def point_id(doc_id: int, page_no: int) -> int:
    return doc_id * 10000 + page_no          # MAX_PAGES <= 9999 keeps ids unique


@contextmanager
def qdrant_errors():
    """Connection problems pause the worker; Qdrant rejecting the data fails the document."""
    try:
        yield
    except (ResponseHandlingException, httpx.TransportError) as e:
        raise Paused("Qdrant is not running: make up") from e
    except UnexpectedResponse as e:
        raise DocError(f"Qdrant: {e}") from e
    except ValueError as e:                  # local mode reports bad vectors as ValueError
        raise DocError(f"Qdrant: {e}") from e


def check_reachable(qc: QdrantClient) -> None:
    with qdrant_errors():
        qc.get_collections()


def collection_exists(qc: QdrantClient, cfg: Config) -> bool:
    with qdrant_errors():
        return qc.collection_exists(cfg.qdrant_collection)


def check_collection(qc: QdrantClient, conn, cfg: Config) -> None:
    """Exit if the stored vectors no longer match the config, or were lost (PLAN.md §4.2)."""
    _pages, requests = store.request_estimate(conn, cfg.embed_batch_pages)
    if collection_exists(qc, cfg):
        meta = qc.get_collection(cfg.qdrant_collection).config.metadata or {}
        for key, want in (("embed_model", cfg.embed_model), ("passage_mode", cfg.passage_mode)):
            if meta.get(key) != want:
                raise SystemExit(f"{key.upper() if key == 'embed_model' else 'Passage mode'} changed from "
                                 f"{meta.get(key)} to {want}: run 'make reembed' (≈ {requests} requests) "
                                 f"or revert .env")
        return
    if embedded := store.pages_embedded(conn):
        raise SystemExit(f"Qdrant collection '{cfg.qdrant_collection}' is missing but {embedded} pages were "
                         f"embedded: run 'make reembed' (≈ {requests} requests)")


def upsert(qc: QdrantClient, cfg: Config, doc_id: int, pages: list[int], vecs: list[list[float]]) -> None:
    """Creates the collection on the first upsert, sized by the first vector."""
    with qdrant_errors():
        if not qc.collection_exists(cfg.qdrant_collection):
            dim = len(vecs[0])
            qc.create_collection(cfg.qdrant_collection,
                                 vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
                                 metadata={"embed_model": cfg.embed_model, "dim": dim,
                                           "passage_mode": cfg.passage_mode})
            with warnings.catch_warnings():  # local mode warns that payload indexes do nothing
                warnings.simplefilter("ignore")
                qc.create_payload_index(cfg.qdrant_collection, field_name="doc_id",
                                        field_schema=models.PayloadSchemaType.INTEGER)
        qc.upsert(cfg.qdrant_collection, wait=True, points=[
            models.PointStruct(id=point_id(doc_id, p), vector=v, payload={"doc_id": doc_id, "page": p})
            for p, v in zip(pages, vecs)])


def search_groups(qc: QdrantClient, cfg: Config, vec: list[float]) -> list[models.PointGroup]:
    """The SEARCH_GROUPS best documents, each with its best pages (enough to fill ANSWER_PAGES, at least 3)."""
    with qdrant_errors():
        return qc.query_points_groups(cfg.qdrant_collection, group_by="doc_id", query=vec, limit=cfg.search_groups,
                                      group_size=max(cfg.answer_pages, 3), with_payload=True).groups


def delete_points(qc: QdrantClient, cfg: Config, doc_id: int) -> None:
    with qdrant_errors():
        if qc.collection_exists(cfg.qdrant_collection):
            qc.delete(cfg.qdrant_collection, points_selector=models.FilterSelector(filter=models.Filter(
                must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])))


def drop_collection(qc: QdrantClient, cfg: Config) -> None:
    with qdrant_errors():
        if qc.collection_exists(cfg.qdrant_collection):
            qc.delete_collection(cfg.qdrant_collection)

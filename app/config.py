import os
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Config:
    openrouter_api_key: str = ""
    openrouter_url: str = "https://openrouter.ai/api/v1"
    embed_model: str = "voyageai/voyage-multimodal-3.5"
    embed_input_mode: str = "field"          # field | prefix
    embed_query_type: str = "query"
    embed_passage_type: str = "document"
    embed_batch_pages: int = 8
    embed_square_pages: bool = False         # pad pages to squares for the embedder (needed by the free Nemotron)
    answer_model: str = "meta/muse-spark-1.3-contributor"
    answer_pages: int = 3
    answer_max_tokens: int = 2048
    or_reserve_requests: int = 10
    or_min_interval_s: float = 3.2
    web_viewport_width: int = 1120
    web_slice_height: int = 1120
    page_longest_edge_px: int = 1536
    jpeg_quality: int = 85
    max_pages: int = 500                     # must stay <= 9999 (point id = doc_id * 10000 + page)
    max_web_pages: int = 40
    max_upload_mb: int = 200
    search_groups: int = 10
    office_extensions: frozenset = frozenset({".docx"})
    gotenberg_url: str = "http://127.0.0.1:3100"
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "pages"
    data_dir: Path = Path("data")

    @property
    def passage_mode(self) -> str:           # stored on the Qdrant collection
        mode = f"field:{self.embed_passage_type}" if self.embed_input_mode == "field" else "prefix"
        return mode + ("+square" if self.embed_square_pages else "")


def load_config(env=None) -> Config:
    env = os.environ if env is None else env
    values = {}
    for f in fields(Config):
        raw = env.get(f.name.upper())
        if raw is None or raw.strip() == "":
            continue
        raw = raw.strip()
        default = f.default
        if isinstance(default, bool):
            values[f.name] = raw.lower() in ("1", "true", "yes")
        elif isinstance(default, int):
            values[f.name] = int(raw)
        elif isinstance(default, float):
            values[f.name] = float(raw)
        elif isinstance(default, frozenset):
            values[f.name] = frozenset(e.strip().lower() for e in raw.split(",") if e.strip())
        elif isinstance(default, Path):
            values[f.name] = Path(raw)
        else:
            values[f.name] = raw
    cfg = Config(**values)
    if cfg.embed_input_mode not in ("field", "prefix"):
        raise SystemExit(f"EMBED_INPUT_MODE must be 'field' or 'prefix', not {cfg.embed_input_mode!r}")
    if not 0 < cfg.max_pages <= 9999 or not 0 < cfg.max_web_pages <= 9999:
        raise SystemExit("MAX_PAGES and MAX_WEB_PAGES must be between 1 and 9999")
    return cfg


def check_key(cfg: Config) -> None:
    if not cfg.openrouter_api_key or cfg.openrouter_api_key.startswith("sk-or-..."):
        raise SystemExit("OPENROUTER_API_KEY is empty or still the placeholder: put your key in .env")

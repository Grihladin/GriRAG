"""The only code that talks to OpenRouter: throttle, free-quota read, 429 classification, errors."""
import base64
import logging
import threading
import time
from datetime import UTC, datetime, timedelta

import httpx

from app.backend.config import Config
from app.backend.errors import DocError, Paused, RateLimited

log = logging.getLogger(__name__)

PRIVACY_HINT = "no endpoints: enable free endpoints at https://openrouter.ai/settings/privacy, or the model was withdrawn"
# The free NVIDIA embedder answers about half of all requests with a random 502 (seen while building the app).
# Failed requests do not count against the free quota, so a 502 is retried right away (through the throttle).
ATTEMPTS_502 = 4
BATCH_HINT = ("if this is about size (image_too_large is a 400, payload_too_large a 413), "
              "lower EMBED_BATCH_PAGES in .env, restart, then Retry")


def next_utc_midnight(now: float | None = None) -> float:
    d = datetime.fromtimestamp(time.time() if now is None else now, UTC)
    return (d.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()


def image_part(jpeg: bytes) -> dict:
    """A JPEG as a message content part (embedding inputs and chat messages)."""
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}}


def _message(r: httpx.Response) -> str:
    try:
        err = r.json().get("error") or {}
        msg = err.get("message") or r.text
        raw = (err.get("metadata") or {}).get("raw")
        return f"{msg} ({raw})" if raw and raw not in msg else msg
    except ValueError:
        return r.text[:500] or f"HTTP {r.status_code}"


class OpenRouter:
    def __init__(self, cfg: Config, http: httpx.Client, clock=time.time, sleep=time.sleep):
        self.cfg, self.http, self.clock, self.sleep = cfg, http, clock, sleep
        self._lock = threading.Lock()
        self._last = 0.0
        self._backoff_k = 0
        self._quota_cache: tuple[float, dict | None] = (0.0, None)

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.cfg.openrouter_api_key}"}

    def _wait_slot(self) -> None:
        with self._lock:                         # the lock never covers network I/O
            slot = max(self.clock(), self._last + self.cfg.or_min_interval_s)
            self._last = slot
        delay = slot - self.clock()
        if delay > 0:
            self.sleep(delay)

    def post(self, path: str, payload: dict, *, timeout: float = 120) -> dict:
        items = payload.get("input")
        what = f"items={len(items) if isinstance(items, list) else 1}" if "input" in payload else ""
        for attempt in range(1, ATTEMPTS_502 + 1):
            self._wait_slot()
            t0 = self.clock()
            try:
                r = self.http.post(self.cfg.openrouter_url + path, json=payload, headers=self.headers,
                                   timeout=timeout)
            except httpx.HTTPError as e:
                log.info("openrouter %s model=%s %s error=%s", path, payload.get("model"), what, type(e).__name__)
                raise Paused(f"OpenRouter unreachable: {type(e).__name__}: {e}") from e
            if r.status_code != 502 or attempt == ATTEMPTS_502:
                break
            log.info("openrouter %s model=%s %s status=502 %.1fs (attempt %d of %d)", path, payload.get("model"),
                     what, self.clock() - t0, attempt, ATTEMPTS_502)
        body = None
        try:
            body = r.json()
        except ValueError:
            pass
        usage = (body or {}).get("usage") or {}
        log.info("openrouter %s model=%s %s status=%s %.1fs tokens=%s cost=%s", path, payload.get("model"), what,
                 r.status_code, self.clock() - t0, usage.get("total_tokens", usage.get("prompt_tokens")),
                 usage.get("cost"))
        if r.status_code == 200 and isinstance(body, dict):
            if body.get("error"):
                err = body["error"]
                raise Paused(f"OpenRouter error: {err.get('message', err)}")
            self._backoff_k = 0
            return body
        self._raise_for(r, path)
        raise Paused(f"OpenRouter returned an unreadable response (HTTP {r.status_code})")

    def _raise_for(self, r: httpx.Response, path: str) -> None:
        s, msg = r.status_code, _message(r)
        if s == 429:
            q = self.free_quota(cached=False)
            if q and q["remaining"] == 0:
                at = next_utc_midnight(self.clock()) + 60
                raise RateLimited(at, "daily free quota reached")
            try:
                retry_after = float(r.headers.get("Retry-After", 0))
            except ValueError:
                retry_after = 0
            wait = min(max(retry_after, 60 * 2 ** self._backoff_k), 3600)
            self._backoff_k += 1
            raise RateLimited(self.clock() + wait, f"rate-limited ({msg}); retrying in {int(wait)} s")
        if s in (400, 413):
            raise DocError(f"{msg}; {BATCH_HINT}" if path == "/embeddings" else msg)
        if s == 401:
            raise Paused(f"OpenRouter 401: check OPENROUTER_API_KEY in .env ({msg})")
        if s == 402:
            raise Paused(f"OpenRouter 402: out of credits for a paid model ({msg})")
        if s == 404:
            raise Paused(f"OpenRouter 404: {PRIVACY_HINT} ({msg})")
        if s == 403:
            raise DocError(f"OpenRouter 403 (moderation): {msg}")
        if s == 200:
            return
        raise Paused(f"OpenRouter HTTP {s}: {msg}")

    def free_quota(self, cached: bool = True) -> dict | None:
        """{"used", "limit", "remaining"} of today's free-model requests, or None if unavailable."""
        at, value = self._quota_cache
        if cached and self.clock() - at < 60:
            return value
        try:
            r = self.http.get(self.cfg.openrouter_url + "/key", headers=self.headers, timeout=15)
            q = r.json()["data"]["free_model_daily_requests"]
            value = {k: int(q[k]) for k in ("used", "limit", "remaining")}
        except Exception:  # noqa: BLE001 -- the quota line is optional
            value = None
        self._quota_cache = (self.clock(), value)
        return value

    def chat(self, model: str, messages: list[dict], *, max_tokens: int | None,
             reasoning_effort: str | None = None,
             temperature: float = 0.4) -> tuple[str, str]:
        payload = {"model": model, "messages": messages, "temperature": temperature}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}
        body = self.post("/chat/completions", payload, timeout=180)
        choice = (body.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        if not content.strip() and choice.get("finish_reason") == "length":
            raise DocError("The model used its whole token budget on reasoning; raise ANSWER_MAX_TOKENS in .env.")
        return content, body.get("model", model)

"""CLI: `smoke` (M0 live checks) and `reembed` (PLAN.md §5.8)."""
import argparse
import dataclasses
import json
import logging
import math
import random
import re
import sys
import time

import httpx
import pymupdf

from app import DocError, Paused, RateLimited
from app.config import Config, check_key, load_config

Q1 = "What is the capital of Freedonia?"
Q2 = "What is the invoice total?"


# ---------------------------------------------------------------- smoke pages (real render settings)

def _render(page: pymupdf.Page, cfg: Config, longest_edge: int) -> bytes:
    z = longest_edge / max(page.rect.width, page.rect.height)
    return page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False).tobytes("jpeg", jpg_quality=cfg.jpeg_quality)


def page_a(cfg: Config) -> bytes:
    """Web-shaped: one 1120 x 1120 px slice, 16 px body text."""
    with pymupdf.open() as doc:
        side = cfg.web_slice_height
        p = doc.new_page(width=side, height=side)
        p.insert_text((60, 90), "Freedonia: travel notes", fontsize=34)
        p.insert_textbox(pymupdf.Rect(60, 130, side - 60, side - 60),
                         "The capital of Freedonia is Plumbury. " + "Plumbury sits on the river Fenn and is known "
                         "for its markets, its old bridge and its harbour. " * 6, fontsize=16)
        return _render(p, cfg, side)


def page_b(cfg: Config) -> bytes:
    """A4 invoice with a 7 pt footnote."""
    with pymupdf.open() as doc:
        p = doc.new_page(width=595, height=842)
        p.insert_text((60, 80), "INVOICE No. 2026-117", fontsize=20)
        p.insert_text((60, 110), "Acme Widgets GmbH, Hauptstrasse 5, Berlin", fontsize=10)
        rows = [("Item", "Qty", "Price"), ("Widget A", "10", "1,200 EUR"), ("Widget B", "4", "2,000 EUR"),
                ("Shipping", "1", "1,112 EUR"), ("Total", "", "4,312 EUR")]
        y = 170
        for i, (a, b, c) in enumerate(rows):
            p.draw_rect(pymupdf.Rect(60, y - 16, 535, y + 6), color=(0, 0, 0), width=0.6)
            for x, t in ((66, a), (330, b), (430, c)):
                p.insert_text((x, y), t, fontsize=12 if i in (0, 4) else 11)
            y += 22
        p.insert_text((60, 800), "Ref. code K7-334-Q  Payable within 30 days.", fontsize=7)
        return _render(p, cfg, cfg.page_longest_edge_px)


def page_noise(cfg: Config, seed: int, block: int = 11) -> bytes:
    """Photo-like page (coloured noise blocks), about 300-500 KB, A4 at the real render size."""
    h = cfg.page_longest_edge_px
    w = round(h * 595 / 842)
    rnd = random.Random(seed)
    sw, sh = w // block, h // block
    small = pymupdf.Pixmap(pymupdf.csRGB, sw, sh, rnd.randbytes(sw * sh * 3), False)
    return pymupdf.Pixmap(small, w, h, None).tobytes("jpeg", jpg_quality=cfg.jpeg_quality)


# ---------------------------------------------------------------- smoke

def cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def smoke(cfg: Config) -> int:
    from app.embedder import OpenRouterEmbedder, image_part, parse_vectors
    from app.main import build_messages
    from app.openrouter import OpenRouter

    check_key(cfg)
    http = httpx.Client()
    orr = OpenRouter(cfg, http)
    emb = OpenRouterEmbedder(cfg, orr)
    sent = ok = 0

    def call(label, path, body):
        nonlocal sent, ok
        sent += 1
        size = len(json.dumps(body)) / 1e6
        try:
            out = orr.post(path, body, timeout=180)
            ok += 1
            return out, size
        except (DocError, Paused, RateLimited) as e:
            print(f"{label}: FAILED ({type(e).__name__}): {e}")
            return None, size

    print(f"config: embed={cfg.embed_model} mode={cfg.embed_input_mode} query_type={cfg.embed_query_type} "
          f"passage_type={cfg.embed_passage_type} batch={cfg.embed_batch_pages} answer={cfg.answer_model}")
    r = http.get(cfg.openrouter_url + "/key", headers={"Authorization": f"Bearer {cfg.openrouter_api_key}"})
    key = r.json().get("data", {})
    q_before = key.get("free_model_daily_requests")
    print(f"key: is_free_tier={key.get('is_free_tier')} free_model_daily_requests={q_before}")

    a, b = page_a(cfg), page_b(cfg)
    bs = cfg.embed_batch_pages
    pages = [a, b] + [page_noise(cfg, s) for s in range(max(bs - 2, 1))]   # at least one heavy page
    print("pages KB:", [len(p) // 1024 for p in pages])

    # request 1 (more if the batch is smaller than the pages): the pages in the configured passage mode
    vecs = []
    for i in range(0, len(pages), bs):
        chunk = pages[i:i + bs]
        out, size = call("embed", "/embeddings", emb._body(emb.page_inputs(chunk), cfg.embed_passage_type))
        if out is None:
            print(f"embed: {len(chunk)} pages, request ≈ {size:.1f} MB failed; rerun with a smaller --batch")
            return 1
        got = parse_vectors(out, len(chunk))
        vecs += got
        print(f"embed: {len(got)} vectors, dim {len(got[0])}, index {[d.get('index') for d in out['data']]}, "
              f"request ≈ {size:.1f} MB")
    pa, pb = vecs[0], vecs[1]

    # request 2: baseline with no mode at all (page A and question 1)
    nomode = {"model": cfg.embed_model, "encoding_format": "float"}
    out, _ = call("baseline", "/embeddings", {**nomode, "input": [{"content": [image_part(a)]},
                                                                    {"content": [{"type": "text", "text": Q1}]}]})
    if out is not None:
        p0, q0 = parse_vectors(out, 2)
    else:
        print("baseline: mixed image+text request rejected; splitting")
        out1, _ = call("baseline-image", "/embeddings", {**nomode, "input": [{"content": [image_part(a)]}]})
        out2, _ = call("baseline-text", "/embeddings", {**nomode, "input": Q1})
        if out1 is None or out2 is None:
            return 1
        p0, q0 = parse_vectors(out1, 1)[0], parse_vectors(out2, 1)[0]

    # request 3: both questions in the configured query mode
    out, _ = call("query", "/embeddings", emb._body([emb.query_input(Q1), emb.query_input(Q2)], cfg.embed_query_type))
    if out is None:
        return 1
    q1, q2 = parse_vectors(out, 2)
    print(f"query: 2 vectors, index {[d.get('index') for d in out['data']]}")

    # request 4: a bogus input_type tells "recognised" from "ignored"
    if cfg.embed_input_mode == "field":
        out, _ = call("bogus", "/embeddings", {**nomode, "input": Q1, "input_type": "bogus-mode"})
        if out is None:
            print("bogus input_type: rejected (400) -> unknown values are rejected; accepted values are recognised")
        else:
            print(f"bogus input_type: accepted; cos(bogus, q0) = {cos(parse_vectors(out, 1)[0], q0):.4f}")

    cq, cp = cos(q1, q0), cos(pa, p0)
    print(f"cos(query, q0) = {cq:.4f}   cos(passage A, p0) = {cp:.4f}")
    if cfg.embed_input_mode == "field":
        if cq < 0.995 and cp < 0.995:
            print("input_type forwarded: yes")
        elif cq >= 0.995 and cp >= 0.995:
            print("input_type forwarded: no -> rerun with EMBED_INPUT_MODE=prefix and compare margins")
        elif cp >= 0.995:
            print("input_type forwarded: query only -> rerun with --passage-type document, "
                  "then --query-type search_query --passage-type search_document")
        else:
            print("input_type forwarded: passage only -> try another --query-type")
    else:
        print("prefix mode: vectors differ from the no-mode baseline" if max(cq, cp) < 0.995 else
              "prefix mode: no effect on at least one side")

    s1a, s1b, s2a, s2b = cos(q1, pa), cos(q1, pb), cos(q2, pa), cos(q2, pb)
    print(f"retrieval: q1 {'A > B' if s1a > s1b else 'A <= B (FAIL)'} (margin {s1a - s1b:+.4f}), "
          f"q2 {'B > A' if s2b > s2a else 'B <= A (FAIL)'} (margin {s2b - s2a:+.4f})")

    # request 5: the answer model
    question = "What is the capital of Freedonia, and what is the reference code in the invoice footnote?"
    msgs = build_messages(question, [("[S1] smoke-web, page 1", a), ("[S2] smoke-invoice.pdf, page 1", b)])
    chat_payload = {"model": cfg.answer_model, "messages": msgs,
                    "max_tokens": cfg.answer_max_tokens, "temperature": cfg.answer_temperature}
    if cfg.answer_reasoning_effort:
        chat_payload["reasoning"] = {"effort": cfg.answer_reasoning_effort}
    out, _ = call("chat", "/chat/completions", chat_payload)
    if out is not None:
        ch = out["choices"][0]
        content = ch["message"].get("content") or ""
        print(f"chat: model={out.get('model')} finish_reason={ch.get('finish_reason')} usage={out.get('usage')}")
        print(f"chat: system message accepted: yes; <think> in content: {'<think>' in content}")
        print("answer:", content.strip())
        for needle in ("Plumbury", "K7-334-Q", "[S1]"):
            print(f"  contains {needle!r}: {needle in content}")

    time.sleep(5)
    r = http.get(cfg.openrouter_url + "/key", headers={"Authorization": f"Bearer {cfg.openrouter_api_key}"})
    q_after = r.json().get("data", {}).get("free_model_daily_requests")
    if q_before and q_after:
        print(f"quota: used {q_before['used']} -> {q_after['used']} (delta {q_after['used'] - q_before['used']}); "
              f"model requests sent {sent}, succeeded {ok}; /key calls 2")
    return 0


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("smoke", help="M0 live checks (about 5 free requests)")
    sp.add_argument("--input-mode", choices=["field", "prefix"])
    sp.add_argument("--query-type")
    sp.add_argument("--passage-type")
    sp.add_argument("--batch", type=int)
    sub.add_parser("reembed", help="drop the collection and re-embed every document at the next start")
    args = ap.parse_args(argv)
    cfg = load_config()
    if args.cmd == "smoke":
        over = {k: v for k, v in (("embed_input_mode", args.input_mode), ("embed_query_type", args.query_type),
                                  ("embed_passage_type", args.passage_type), ("embed_batch_pages", args.batch))
                if v is not None}
        return smoke(dataclasses.replace(cfg, **over))
    from app.ingest import reembed
    return reembed(cfg)


if __name__ == "__main__":
    sys.exit(main())

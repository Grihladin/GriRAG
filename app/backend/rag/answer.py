"""Ask: send the best pages to the vision model and get an answer with [S1]-style citations."""
import re
from dataclasses import dataclass

from app.backend import store
from app.backend.deps import Deps
from app.backend.errors import DocError, Paused, RateLimited
from app.backend.rag.openrouter import image_part
from app.backend.rag.search import Hit, search, user_message

# Adapted from PixelRAG's SYSTEM_PROMPT_EVIDENCE_QA, without its <think> instruction. Research (agent.py) uses it with
# [#120003] labels instead of [S1].
PROMPT = """You answer questions using only the document pages shown as images.
Each image is preceded by a label such as {a}.
After each statement, cite the label(s) of the page(s) it comes from, e.g. "The total is 4,312 EUR {b}."
If the pages do not contain the answer, reply "Not found in the retrieved pages." and stop.
Be concise. Answer in the language of the question."""
SYSTEM_PROMPT = PROMPT.format(a="[S1]", b="[S2]")


@dataclass
class Answer:
    text: str
    sources: list[Hit]               # [S1] is sources[0]
    model: str
    groups: list[list[Hit]]          # every matching page, as search() returns them


def build_messages(question: str, pages: list[tuple[str, bytes]], system: str = SYSTEM_PROMPT) -> list[dict]:
    """pages: (label, jpeg) in citation order, e.g. ("[S1] invoice.pdf, page 2", b"...")."""
    content = [{"type": "text", "text": f"Question: {question}"}]
    for label, jpeg in pages:
        content += [{"type": "text", "text": label}, image_part(jpeg)]
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


def read(deps: Deps, question: str, pages: list[tuple[str, bytes]],
         system: str = SYSTEM_PROMPT, max_tokens: int | None = None) -> tuple[str, str] | str:
    """The vision model's answer from labelled pages, as (text, model); or a message for the user. Never retried.
    Without max_tokens the output has no limit of ours."""
    cfg = deps.cfg
    try:
        content, model = deps.openrouter.chat(cfg.answer_model, build_messages(question.strip(), pages, system),
                                              max_tokens=max_tokens,
                                              reasoning_effort=cfg.answer_reasoning_effort,
                                              temperature=cfg.answer_temperature)
    except (DocError, Paused, RateLimited) as e:
        return user_message(e)
    return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip(), model


def ask(deps: Deps, conn, question: str) -> Answer | str:
    """Answer from the ANSWER_PAGES best pages overall; or a message for the user. Never retried automatically."""
    groups = search(deps, conn, question)
    if isinstance(groups, str):
        return groups
    if not groups:
        return "No matching pages."
    cfg = deps.cfg
    sources = sorted((h for g in groups for h in g), key=lambda h: h.score, reverse=True)[:cfg.answer_pages]
    pages = [(f"[S{i}] {h.title}, page {h.page_no}", store.page_path(cfg, h.doc_id, h.page_no).read_bytes())
             for i, h in enumerate(sources, start=1)]
    result = read(deps, question, pages, max_tokens=cfg.answer_max_tokens)
    if isinstance(result, str):
        return result
    text, model = result
    return Answer(text, sources, model, groups)

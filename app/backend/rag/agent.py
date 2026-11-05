"""Research: a multi-turn agent (deepagents) that searches, has the vision model read pages, and cites them as [#id].

The agent model only plans and writes text; read_pages sends the page images to ANSWER_MODEL. Conversations are
LangGraph checkpoints in data/agent.db, keyed by the thread id the UI keeps in its URL. A page's id is its Qdrant point
id (doc_id * 10000 + page), so citations stay valid for the whole conversation without extra state."""
from contextlib import closing
from typing import Any

from assistant_stream import RunController, create_run
from assistant_stream.modules.langgraph import append_langgraph_event
from assistant_stream.serialization import AssistantTransportResponse
from deepagents import create_deep_agent
from fastapi import APIRouter, Request
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openrouter import ChatOpenRouter
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel

from app.backend import store
from app.backend.deps import Deps
from app.backend.rag.answer import PROMPT, read
from app.backend.rag.search import search
from app.backend.rag.vectors import point_id

READER_PROMPT = PROMPT.format(a="[#120003]", b="[#120003]")
SYSTEM_PROMPT = """You answer questions about the user's document library. You cannot see the pages yourself.
1. Call search_pages to find candidate pages. Try a few reformulated queries (synonyms, the document's language, \
key terms) when the first one is not clearly right.
2. Call read_pages with the most promising ids and a precise question; it returns what those pages say, citing [#id].
3. Answer only from what read_pages returned. After each statement cite the page(s) as [#id], e.g. "The total is \
4,312 EUR [#120003]." Never cite a page read_pages did not report on.
If the pages do not contain the answer, say so plainly. Be concise. Answer in the language of the question.
Follow-up questions may refer to earlier answers and pages: reuse their ids instead of searching again when they fit."""


def make_tools(deps: Deps) -> list:
    cfg = deps.cfg

    @tool
    def search_pages(query: str) -> str:
        """Find the library pages that best match a query. One line per page, best first: #<id> <title> p.<page> (<score>)."""
        with closing(deps.connect()) as conn:
            groups = search(deps, conn, query)
        if isinstance(groups, str):
            return groups
        hits = sorted((h for g in groups for h in g), key=lambda h: h.score, reverse=True)[:2 * cfg.answer_pages]
        return "\n".join(f"#{point_id(h.doc_id, h.page_no)} {h.title} p.{h.page_no} ({h.score:.2f})"
                         for h in hits) or "No matching pages."

    @tool(description=f"Show up to {cfg.answer_pages} pages (ids from search_pages) to a vision model and get what "
                      "they say about the question, with [#id] citations.")
    def read_pages(question: str, ids: list[int]) -> str:
        ids = list(dict.fromkeys(ids))[:cfg.answer_pages]
        with closing(deps.connect()) as conn:
            rows = store.by_ids(conn, list({i // 10000 for i in ids}))
        pages = []
        for i in ids:
            doc_id, page = divmod(i, 10000)
            path = store.page_path(cfg, doc_id, page)
            if doc_id in rows and path.exists():
                pages.append((f"[#{i}] {rows[doc_id]['title']}, page {page}", path.read_bytes()))
        if not pages:
            return "None of these ids is a page in the library; use ids from search_pages."
        result = read(deps, question, pages, READER_PROMPT)
        return result if isinstance(result, str) else result[0]

    return [search_pages, read_pages]


def build(deps: Deps, checkpointer, model: BaseChatModel | None = None):
    """The compiled agent. Interactive requests are never retried automatically (max_retries=0)."""
    cfg = deps.cfg
    model = model or ChatOpenRouter(model=cfg.agent_model, temperature=cfg.agent_temperature, max_retries=0,
                                    api_key=cfg.openrouter_api_key, base_url=cfg.openrouter_url, timeout=180_000,
                                    app_title="GriRAG", app_url="https://github.com/Grihladin/GriRAG")
    return create_deep_agent(model=model, tools=make_tools(deps), system_prompt=SYSTEM_PROMPT,
                             checkpointer=checkpointer)


def error_text(e: Exception, max_steps: int) -> str:
    if isinstance(e, GraphRecursionError):
        return f"Stopped after {max_steps} steps (AGENT_MAX_STEPS). Ask a narrower question, or raise it in .env."
    hint = {401: "check OPENROUTER_API_KEY in .env", 402: "out of credits", 404: "the model was not found",
            429: "rate-limited, try again in a minute"}.get(getattr(e, "status_code", None))
    return f"The agent model failed: {hint + ' (' + str(e) + ')' if hint else e}"


# ---------------------------------------------------------------- routes (assistant-ui's Assistant Transport)

router = APIRouter(prefix="/api/agent")


class Part(BaseModel):
    type: str
    text: str | None = None


class Message(BaseModel):
    id: str | None = None
    parts: list[Part] = []


class Command(BaseModel):
    type: str
    message: Message | None = None


class AgentRequest(BaseModel):
    thread_id: str
    commands: list[Command]
    state: dict[str, Any] | None = None


@router.post("")
async def run_agent(body: AgentRequest, request: Request) -> AssistantTransportResponse:
    """Streams the conversation state ({"messages": [LangChain message dicts]}) while the agent works."""
    agent, cfg = request.app.state.agent, request.app.state.deps.cfg
    inputs = [HumanMessage(content=text, id=c.message.id) for c in body.commands
              if c.type == "add-message" and c.message
              and (text := " ".join(p.text for p in c.message.parts if p.type == "text" and p.text).strip())]

    async def run(controller: RunController) -> None:
        if controller.state is None or "messages" not in controller.state:
            controller.state = {"messages": []}
        for m in inputs:
            controller.state["messages"].append(m.model_dump())
        if not inputs:
            return
        config = {"configurable": {"thread_id": body.thread_id}, "recursion_limit": cfg.agent_max_steps}
        try:
            async for namespace, kind, chunk in agent.astream({"messages": inputs}, config=config,
                                                              stream_mode=["messages"], subgraphs=True):
                if not namespace:                # the main agent only, not the inside of a subagent
                    append_langgraph_event(controller.state, namespace, kind, chunk)
        except Exception as e:  # noqa: BLE001 -- shown in the conversation instead of breaking the stream
            controller.add_error(error_text(e, cfg.agent_max_steps))

    return AssistantTransportResponse(create_run(run, state=body.state))


@router.get("/{thread_id}")
async def history(thread_id: str, request: Request) -> dict:
    """The saved conversation, in the shape the stream uses, so a page reload restores it."""
    snapshot = await request.app.state.agent.aget_state({"configurable": {"thread_id": thread_id}})
    return {"messages": [m.model_dump() for m in snapshot.values.get("messages", [])]}

"""Research: the two tools, and /api/agent with a fake chat model (no network)."""
import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.backend.errors import Paused
from app.backend.main import app
from app.backend.rag import agent
from tests.test_api import Worker
from tests.test_query import library, query_matching


def tools(deps):
    return {t.name: t for t in agent.make_tools(deps)}


# ---------------------------------------------------------------- search_pages

def test_search_pages_lists_point_ids(deps, conn):
    library(deps, conn, "sample.pdf", "sample2.pdf")
    query_matching(deps, 1, 2)
    lines = tools(deps)["search_pages"].invoke({"query": "invoice total"}).splitlines()
    assert lines[0] == "#10002 sample.pdf p.2 (1.00)"
    assert len(lines) == 6 and all(line.startswith("#") for line in lines)


def test_search_pages_messages(deps):
    assert tools(deps)["search_pages"].invoke({"query": "invoice total"}) == "No documents yet."


# ---------------------------------------------------------------- read_pages

def test_read_pages_labels_and_caps(deps, conn):
    library(deps, conn, "sample.pdf", "sample2.pdf")
    deps.cfg = deps.cfg.__class__(**{**deps.cfg.__dict__, "answer_pages": 2})
    deps.openrouter.reply = "<think>hm</think>The total is 4,312 EUR [#10002]."
    read = tools(deps)["read_pages"]
    assert "Show up to 2 pages" in read.description
    assert read.invoke({"question": "Total?", "ids": [10002, 10002, 20001, 10003]}) == "The total is 4,312 EUR [#10002]."
    system, user = deps.openrouter.chats[0]
    assert "[#120003]" in system["content"] and "[S1]" not in system["content"]
    labels = [p["text"] for p in user["content"] if p["type"] == "text"]
    assert labels == ["Question: Total?", "[#10002] sample.pdf, page 2", "[#20001] sample2.pdf, page 1"]


def test_read_pages_has_no_output_limit(deps, conn):
    library(deps, conn, "sample.pdf")
    tools(deps)["read_pages"].invoke({"question": "x", "ids": [10001]})
    assert deps.openrouter.max_tokens is None


def test_read_pages_unknown_ids_make_no_request(deps, conn):
    library(deps, conn, "sample.pdf")
    assert "None of these ids" in tools(deps)["read_pages"].invoke({"question": "x", "ids": [990001, 10099]})
    assert deps.openrouter.chats == []


def test_read_pages_errors_become_text(deps, conn):
    library(deps, conn, "sample.pdf")
    deps.openrouter.error = Paused("OpenRouter 402: out of credits for a paid model (x)")
    assert "402" in tools(deps)["read_pages"].invoke({"question": "x", "ids": [10001]})


# ---------------------------------------------------------------- /api/agent

class FakeModel(GenericFakeChatModel):
    """Replies with the given messages in turn. Not streamed: GenericFakeChatModel can't stream a bare tool call."""
    disable_streaming: bool = True

    def bind_tools(self, tools, **kwargs):
        return self


def scripted(*messages):
    return FakeModel(messages=iter(messages))


def search_then_answer():
    return scripted(
        AIMessage("", tool_calls=[{"id": "call_1", "name": "search_pages", "args": {"query": "invoice total"}}]),
        AIMessage("The total is 4,312 EUR [#10002]."),
        AIMessage("It is due on 1 May [#10002]."))


@pytest.fixture
def client(deps):
    app.state.deps, app.state.worker = deps, Worker()
    return TestClient(app)


def send(client, thread_id, text, state=None):
    """The body useAssistantTransportRuntime sends (research-page.tsx adds thread_id)."""
    body = {"thread_id": thread_id, "state": state or {"messages": []}, "system": None, "tools": {},
            "callSettings": {}, "config": {}, "threadId": "__LOCALID_x",
            "commands": [{"type": "add-message", "parentId": None, "sourceId": None,
                          "message": {"role": "user", "id": f"u{len(text)}", "parts": [{"type": "text", "text": text}]}}]}
    r = client.post("/api/agent", json=body)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    frames = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: {")]
    assert r.text.rstrip().endswith("data: [DONE]")
    return frames


def test_agent_streams_and_keeps_history(client, deps, conn):
    library(deps, conn, "sample.pdf")
    app.state.agent = agent.build(deps, InMemorySaver(), model=search_then_answer())
    frames = send(client, "t1", "What is the invoice total?")
    ops = [op for f in frames if f["type"] == "update-state" for op in f["operations"]]
    assert "4,312" in json.dumps(ops)
    assert not [f for f in frames if f["type"] == "error"]

    history = client.get("/api/agent/t1").json()["messages"]
    assert [m["type"] for m in history] == ["human", "ai", "tool", "ai"]
    assert history[0]["content"] == "What is the invoice total?"
    assert history[1]["tool_calls"][0]["name"] == "search_pages"
    assert history[2]["content"].startswith("#1000")
    assert history[3]["content"] == "The total is 4,312 EUR [#10002]."
    assert client.get("/api/agent/other").json() == {"messages": []}

    # A follow-up in the same conversation: the model gets the earlier turn from the checkpointer.
    send(client, "t1", "And when is it due?", state={"messages": history})
    history = client.get("/api/agent/t1").json()["messages"]
    assert [m["type"] for m in history] == ["human", "ai", "tool", "ai", "human", "ai"]
    assert history[-1]["content"] == "It is due on 1 May [#10002]."


def test_agent_model_errors_are_shown(client, deps):
    class Failing(FakeModel):
        def _generate(self, *a, **kw):
            raise type("PaymentRequired", (Exception,), {"status_code": 402})("Insufficient credits")
    app.state.agent = agent.build(deps, InMemorySaver(), model=Failing(messages=iter([])))
    frames = send(client, "t2", "Anything?")
    assert [f["error"] for f in frames if f["type"] == "error"] == [
        "The agent model failed: out of credits (Insufficient credits)"]

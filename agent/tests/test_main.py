import json

import httpx
import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel


def _events(stream: str) -> list[dict]:
    out = []
    for line in stream.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        out.append(json.loads(line.removeprefix("data: ")))
    return out


def text_of(stream: str) -> str:
    """The answer, reassembled from the data-stream's text-delta events."""
    return "".join(e["delta"] for e in _events(stream) if e.get("type") == "text-delta")


def errors_of(stream: str) -> list[str]:
    """The error events the stream carried."""
    return [e["errorText"] for e in _events(stream) if e.get("type") == "error"]


@pytest.fixture
async def client(database_url, monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    import importlib

    import main

    importlib.reload(main)
    async with main.lifespan(main.app):
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c, main


async def test_health_reports_model_and_database(client):
    c, _ = client
    r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "model": "test", "database": True}


async def test_chat_streams_a_reply(client):
    c, main = client
    with main.app.state.agent.override(
        model=TestModel(call_tools=[], custom_output_text="Hello from Scrooge")
    ):
        body = {
            "id": "chat1",
            "trigger": "submit-message",
            "messageId": "m1",
            "messages": [
                {"id": "u1", "role": "user", "parts": [{"type": "text", "text": "hi"}]}
            ],
        }
        r = await c.post("/chat", json=body)
    assert r.status_code == 200
    assert r.headers.get("x-vercel-ai-ui-message-stream") == "v1"
    text = r.text
    # The model's reply arrives one delta at a time, so it is the joined
    # deltas, not the raw stream, that holds the sentence.
    assert text_of(text) == "Hello from Scrooge"
    assert "[DONE]" in text


async def test_chat_stops_a_looping_model_and_says_so(client):
    c, main = client
    calls = 0

    async def stream_fn(messages: list[ModelMessage], info: AgentInfo):
        # A model that only ever calls a tool again, the loop #10 ran into.
        nonlocal calls
        calls += 1
        yield {
            0: DeltaToolCall(name="coverage", json_args="{}", tool_call_id=f"c{calls}")
        }

    with main.app.state.agent.override(model=FunctionModel(stream_function=stream_fn)):
        body = {
            "id": "chat2",
            "trigger": "submit-message",
            "messageId": "m1",
            "messages": [
                {
                    "id": "u1",
                    "role": "user",
                    "parts": [{"type": "text", "text": "capita?"}],
                }
            ],
        }
        r = await c.post("/chat", json=body)
    assert r.status_code == 200
    # The stream carries our sentence, not the library's `request_limit` text.
    assert errors_of(r.text) == [main.LIMIT_MESSAGE]
    assert "request_limit" not in r.text


async def test_chat_without_database_is_a_clear_500(database_url, monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "test")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import importlib

    import main

    importlib.reload(main)
    async with main.lifespan(main.app):
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post(
                "/chat", json={"id": "x", "trigger": "submit-message", "messages": []}
            )
    assert r.status_code == 500
    assert "DATABASE_URL" in r.json()["error"]

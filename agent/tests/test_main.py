import json

import httpx
import pytest
from pydantic_ai.models.test import TestModel


def text_of(stream: str) -> str:
    """The answer, reassembled from the data-stream's text-delta events."""
    deltas = []
    for line in stream.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        event = json.loads(line.removeprefix("data: "))
        if event.get("type") == "text-delta":
            deltas.append(event["delta"])
    return "".join(deltas)


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
    with main.app.state.agent.override(model=TestModel(call_tools=[], custom_output_text="Hello from Scrooge")):
        body = {
            "id": "chat1",
            "trigger": "submit-message",
            "messageId": "m1",
            "messages": [{"id": "u1", "role": "user", "parts": [{"type": "text", "text": "hi"}]}],
        }
        r = await c.post("/chat", json=body)
    assert r.status_code == 200
    assert r.headers.get("x-vercel-ai-ui-message-stream") == "v1"
    text = r.text
    # The model's reply arrives one delta at a time, so it is the joined
    # deltas, not the raw stream, that holds the sentence.
    assert text_of(text) == "Hello from Scrooge"
    assert "[DONE]" in text


async def test_chat_without_database_is_a_clear_500(database_url, monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "test")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import importlib

    import main

    importlib.reload(main)
    async with main.lifespan(main.app):
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post("/chat", json={"id": "x", "trigger": "submit-message", "messages": []})
    assert r.status_code == 500
    assert "DATABASE_URL" in r.json()["error"]

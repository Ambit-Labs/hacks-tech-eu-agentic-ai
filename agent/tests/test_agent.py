import time

import pytest
from pydantic_ai.exceptions import UsageLimitExceeded, UserError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from agent import (
    COVERAGE_TTL_SECONDS,
    INSTRUCTIONS,
    REQUEST_LIMIT,
    USAGE_LIMITS,
    build_agent,
    build_model,
)
from config import Settings
from db import Database
from tools import Deps


@pytest.fixture
async def deps(database_url):
    db = Database(database_url)
    await db.open()
    yield Deps(db=db)
    await db.close()


def test_build_model_test_string():
    model = build_model(Settings(model="test", google_api_key=None, database_url=None, environment="dev"))
    assert isinstance(model, TestModel)


def test_build_model_google_needs_key():
    with pytest.raises(RuntimeError, match="GOOGLE_AI_STUDIO_KEY"):
        build_model(Settings(model="google:gemini-3.8-flash", google_api_key=None, database_url=None, environment="dev"))


def test_build_model_google_with_key():
    model = build_model(Settings(model="google:gemini-3.8-flash", google_api_key="k", database_url=None, environment="dev"))
    assert model.model_name == "gemini-3.8-flash"


def test_build_model_gateway_needs_key(monkeypatch):
    monkeypatch.delenv("PYDANTIC_AI_GATEWAY_API_KEY", raising=False)
    with pytest.raises(UserError, match="PYDANTIC_AI_GATEWAY_API_KEY"):
        build_model(
            Settings(
                model="gateway/google-cloud:gemini-3.6-flash",
                google_api_key=None,
                database_url=None,
                environment="dev",
            )
        )


def test_the_voice_never_outranks_the_facts():
    """The dry voice is decoration. A model follows whichever instruction is
    more vivid, so the accuracy rules come first, the voice section says so,
    and its limits are spelled out: one aside, aimed at process, never at a
    named body, and absent when a joke would land on people."""
    accuracy = INSTRUCTIONS.index("Answer only from the tools.")
    voice = INSTRUCTIONS.index("Voice.")
    assert accuracy < voice
    section = " ".join(INSTRUCTIONS[voice:].split())
    assert "Everything above outranks this section" in section
    assert "never more than one per answer" in section
    assert "Never aim it at a named borough, supplier or person" in section
    assert "never suggest waste, incompetence or wrongdoing" in section
    assert "A caveat about coverage is a plain statement" in section
    assert "social care, children, homelessness" in section


async def test_instructions_carry_coverage(deps):
    agent = build_agent(TestModel(call_tools=[], custom_output_text="ok"))
    result = await agent.run("hi", deps=deps)
    first = result.all_messages()[0]
    assert isinstance(first, ModelRequest)
    assert "camden: 2019-09 to 2019-10, 10 payments" in (first.instructions or "")
    assert "islington: 2019-09 to 2019-10, 8 payments" in (first.instructions or "")


async def test_coverage_is_read_once_per_ttl(deps):
    agent = build_agent(TestModel(call_tools=[], custom_output_text="ok"))
    await agent.run("hi", deps=deps)

    class Refuses:
        async def fetch_all(self, sql, params=None):
            raise AssertionError("coverage must come from the cache")

    deps.db = Refuses()
    result = await agent.run("hi again", deps=deps)
    first = result.all_messages()[0]
    assert isinstance(first, ModelRequest)
    assert "camden: 2019-09 to 2019-10, 10 payments" in (first.instructions or "")


async def test_stale_coverage_is_refreshed(deps):
    deps.coverage_text = "stale"
    deps.coverage_at = time.monotonic() - COVERAGE_TTL_SECONDS - 1
    agent = build_agent(TestModel(call_tools=[], custom_output_text="ok"))
    result = await agent.run("hi", deps=deps)
    instructions = result.all_messages()[0].instructions or ""
    assert "camden: 2019-09 to 2019-10, 10 payments" in instructions
    assert "stale" not in instructions


async def test_tool_call_reaches_the_database(deps):
    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        last = messages[-1]
        if any(isinstance(p, ToolReturnPart) for p in last.parts):
            return ModelResponse(parts=[TextPart("Camden spent £10,000 in September 2019 across 6 payments.")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "spend_total",
                    {"borough": "camden", "period_from": "2019-09-01", "period_to": "2019-09-30"},
                )
            ]
        )

    agent = build_agent(FunctionModel(model_fn))
    result = await agent.run("How much did Camden spend in September 2019?", deps=deps)
    assert result.output.startswith("Camden spent")
    returns = [
        p for m in result.all_messages() if isinstance(m, ModelRequest)
        for p in m.parts if isinstance(p, ToolReturnPart)
    ]
    assert len(returns) == 1
    assert returns[0].content.total_gbp == 10000.0
    assert returns[0].content.payments == 6


async def test_a_looping_model_stops_at_the_request_limit(deps):
    # USAGE_LIMITS is what main.py hands the adapter, so this is the cap a
    # question really runs under, not a number invented for the test.
    requests = 0

    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        return ModelResponse(parts=[ToolCallPart("coverage", {})])

    agent = build_agent(FunctionModel(model_fn))
    with pytest.raises(UsageLimitExceeded) as caught:
        await agent.run("how much to capita?", deps=deps, usage_limits=USAGE_LIMITS)
    assert f"request_limit of {REQUEST_LIMIT}" in str(caught.value)
    assert requests == REQUEST_LIMIT


async def test_every_tool_is_registered(deps):
    calls = set()

    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.update(t.name for t in info.function_tools)
        return ModelResponse(parts=[TextPart("done")])

    await build_agent(FunctionModel(model_fn)).run("hi", deps=deps)
    assert calls == {
        "coverage",
        "spend_total",
        "spend_by",
        "supplier_payments",
        "largest_payments",
        "search_payments",
        "compare_boroughs",
    }

import pytest
from pydantic_ai.exceptions import UserError
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

from agent import build_agent, build_model
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


async def test_instructions_carry_coverage(deps):
    agent = build_agent(TestModel(call_tools=[], custom_output_text="ok"))
    result = await agent.run("hi", deps=deps)
    first = result.all_messages()[0]
    assert isinstance(first, ModelRequest)
    assert "camden: 2019-09 to 2019-10, 10 payments" in (first.instructions or "")
    assert "islington: 2019-09 to 2019-10, 8 payments" in (first.instructions or "")


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

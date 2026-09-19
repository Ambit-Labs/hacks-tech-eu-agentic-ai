"""The agent: model, instructions and tools.

Instructions come in two parts. The static text says what the agent is and
how to answer. The dynamic part lists which boroughs and months are loaded,
so the model can decline a question about data it does not have instead of
guessing. That summary costs about a second over the full dataset, so it is
cached in the deps for COVERAGE_TTL_SECONDS rather than read per request.
"""

from __future__ import annotations

import time

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from config import GOOGLE_KEY_ENV, Settings
from tools import ALL_TOOLS, Deps

GOOGLE_PREFIX = "google:"

# How long the coverage summary stays good. A load adds months, and the next
# question five minutes later sees them.
COVERAGE_TTL_SECONDS = 300

INSTRUCTIONS = """\
You are Scrooge, an assistant that answers questions about what London
boroughs spend, from the payments each borough publishes under the
transparency code (every payment over £500, over £250 in some boroughs).

Answer only from the tools. Never estimate a number you did not get from a
tool. Every answer states the borough, the period and how many payments the
figure covers. When a department or purpose filter was used, name the values
it matched, because every borough labels these differently. When the data
does not cover the borough or period asked, say so and answer for the closest
period that is loaded.

Borough names are lower-case slugs such as camden or tower-hamlets. Financial
years run April to March. Amounts are pounds sterling, net of VAT where the
borough says so. Write short markdown: a sentence or two, and a table when
there are more than three numbers. Do not repeat the raw rows; the reader
sees them in the tool result.
"""


def build_model(settings: Settings) -> Model:
    """The model named by AGENT_MODEL.

    `google:<name>` is built by hand so the key can come from
    GOOGLE_AI_STUDIO_KEY rather than the env var the provider reads on its
    own. Every other string, including `test` and `gateway/...`, goes through
    Pydantic AI's own inference and its own env vars. Inference is also the
    guard for the default model: a `gateway/...` string with no
    PYDANTIC_AI_GATEWAY_API_KEY in the environment raises a `UserError`
    naming that variable, so the server fails at startup rather than on the
    first question.
    """
    if settings.model.startswith(GOOGLE_PREFIX):
        if not settings.google_api_key:
            raise RuntimeError(f"{GOOGLE_KEY_ENV} is not set.")
        return GoogleModel(
            settings.model.removeprefix(GOOGLE_PREFIX),
            provider=GoogleProvider(api_key=settings.google_api_key),
        )
    return infer_model(settings.model)


def build_agent(model: Model) -> Agent[Deps, str]:
    agent: Agent[Deps, str] = Agent(
        model,
        deps_type=Deps,
        instructions=INSTRUCTIONS,
        tools=ALL_TOOLS,
        name="scrooge",
    )

    @agent.instructions
    async def loaded_data(ctx: RunContext[Deps]) -> str:
        deps = ctx.deps
        age = time.monotonic() - deps.coverage_at
        if deps.coverage_text is not None and age < COVERAGE_TTL_SECONDS:
            return deps.coverage_text
        rows = await deps.db.fetch_all(
            "SELECT borough, min(month) AS first, max(month) AS last, sum(payments) AS payments"
            " FROM coverage GROUP BY borough ORDER BY borough"
        )
        if not rows:
            text = "No data is loaded yet. Say so; do not answer with numbers."
        else:
            lines = [
                f"{r['borough']}: {r['first']:%Y-%m} to {r['last']:%Y-%m}, {r['payments']:,} payments"
                for r in rows
            ]
            text = "Data loaded, by borough:\n" + "\n".join(lines)
        deps.coverage_text = text
        deps.coverage_at = time.monotonic()
        return text

    return agent

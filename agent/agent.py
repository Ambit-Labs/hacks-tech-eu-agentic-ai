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
from pydantic_ai.usage import UsageLimits

from config import GOOGLE_KEY_ENV, Settings
from tools import ALL_TOOLS, Deps

GOOGLE_PREFIX = "google:"

# How long the coverage summary stays good. A load adds months, and the next
# question five minutes later sees them.
COVERAGE_TTL_SECONDS = 300

# How many model requests one question gets. A question needs one to four tool
# calls; past that the model is looping over the same tool rather than
# answering, and Pydantic AI's own default of 50 lets it loop for five minutes
# before the user hears anything. Every caller passes USAGE_LIMITS.
REQUEST_LIMIT = 12
USAGE_LIMITS = UsageLimits(request_limit=REQUEST_LIMIT)

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

A question about one supplier goes to supplier_payments. It matches whole
words of the name, and one call covers every borough: it returns the total,
the count, the first and last date, and the total each borough paid. Never
call it once per borough or once per year. When a tool result is large,
summarise what it already says instead of asking the same tool again.

Borough names are lower-case slugs such as camden or tower-hamlets. Financial
years run April to March. Amounts are pounds sterling, net of VAT where the
borough says so. The interface draws every tool result beside your answer, as
a chart or a table, so write the takeaway in a sentence or two of plain
markdown: what the figure is, and what stands out about it. Do not write
tables and do not list the rows.
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

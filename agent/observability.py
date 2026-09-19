"""Logfire setup. One call at startup, before the app serves anything.

With no LOGFIRE_TOKEN in the environment nothing is sent and nothing fails,
so tests and a fresh checkout run without an account. With a token, every
request is one trace: the FastAPI span, the agent run under it, each model
and tool call, and each SQL statement the tools run.
"""

from __future__ import annotations

import logfire
from fastapi import FastAPI

from config import Settings

SERVICE_NAME = "scrooge-agent"


def setup(settings: Settings, app: FastAPI) -> None:
    logfire.configure(
        service_name=SERVICE_NAME,
        environment=settings.environment,
        send_to_logfire="if-token-present",
        console=False,
    )
    # Full prompts, tool arguments and results: the data is public spending
    # records, and readable traces are the point.
    logfire.instrument_pydantic_ai(include_content=True)
    logfire.instrument_fastapi(app)
    logfire.instrument_psycopg()

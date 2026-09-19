"""The chat agent, served over HTTP.

`POST /chat` takes AI SDK messages and streams the answer back in the Vercel
data-stream protocol, which the web app's `useChat` reads. The agent's tools
query Postgres; the lifespan opens the pool and builds the one `Deps` every
run shares.

`app` is a module-level FastAPI instance because Vercel's Python runtime
looks for that name in `main.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.ui import UIEventStream
from pydantic_ai.ui.vercel_ai import VercelAIAdapter, VercelAIEventStream
from pydantic_ai.ui.vercel_ai.response_types import BaseChunk
from starlette.requests import Request
from starlette.responses import Response

import observability
from agent import REQUEST_LIMIT, USAGE_LIMITS, build_agent, build_model
from config import DATABASE_URL_ENV, Settings
from db import Database
from tools import Deps

# The web app runs AI SDK 7. The adapter's v7 wire is identical to v6's today,
# but passing the client's real major keeps both ends on the same value.
SDK_VERSION = 7

# What the reader sees when a run hits REQUEST_LIMIT. The library's own text
# quotes `request_limit` and links its docs, which tells a reader nothing.
LIMIT_MESSAGE = (
    f"I stopped after {REQUEST_LIMIT} steps without reaching an answer. That usually means the"
    " question needs narrowing: name the borough, the period or the supplier and ask again."
)


class ScroogeEventStream(VercelAIEventStream):
    """The Vercel event stream, with our own words for the request limit."""

    async def on_error(self, error: Exception) -> AsyncIterator[BaseChunk]:
        if isinstance(error, UsageLimitExceeded):
            error = RuntimeError(LIMIT_MESSAGE)
        async for chunk in super().on_error(error):
            yield chunk


class ScroogeAdapter(VercelAIAdapter[Deps, str]):
    """The Vercel adapter, streaming through ScroogeEventStream."""

    def build_event_stream(self) -> UIEventStream:
        return ScroogeEventStream(
            self.run_input,
            accept=self.accept,
            sdk_version=self.sdk_version,
            server_message_id=self.server_message_id,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_env()
    app.state.settings = settings
    app.state.agent = build_agent(build_model(settings))
    app.state.db = None
    app.state.deps = None
    if settings.database_url:
        app.state.db = Database(settings.database_url)
        await app.state.db.open()
        # One Deps for the process, so the coverage summary in the
        # instructions is read once every few minutes and not per request.
        app.state.deps = Deps(db=app.state.db)
    try:
        yield
    finally:
        if app.state.db is not None:
            await app.state.db.close()


app = FastAPI(lifespan=lifespan)
observability.setup(Settings.from_env(), app)


def _error(message: str, status: int = 500) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


@app.post("/chat")
async def chat(request: Request) -> Response:
    deps: Deps | None = request.app.state.deps
    if deps is None:
        return _error(
            f"The server is missing {DATABASE_URL_ENV}. Add it to .env.local and restart the agent."
        )
    return await ScroogeAdapter.dispatch_request(
        request,
        agent=request.app.state.agent,
        deps=deps,
        sdk_version=SDK_VERSION,
        usage_limits=USAGE_LIMITS,
    )


@app.get("/health")
async def health(request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "model": settings.model,
        "database": request.app.state.db is not None,
    }

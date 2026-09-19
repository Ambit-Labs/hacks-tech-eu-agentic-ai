"""The chat agent, served over HTTP.

`POST /chat` takes AI SDK messages and streams the answer back in the Vercel
data-stream protocol, which the web app's `useChat` reads. The agent's tools
query Postgres; the pool is opened in the lifespan and handed to each run as
deps.

`app` is a module-level FastAPI instance because Vercel's Python runtime
looks for that name in `main.py`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from starlette.requests import Request
from starlette.responses import Response

import observability
from agent import build_agent, build_model
from config import DATABASE_URL_ENV, Settings
from db import Database
from tools import Deps

# The web app runs AI SDK 7. The adapter's v7 wire is identical to v6's today,
# but passing the client's real major keeps both ends on the same value.
SDK_VERSION = 7


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_env()
    app.state.settings = settings
    app.state.agent = build_agent(build_model(settings))
    app.state.db = None
    if settings.database_url:
        app.state.db = Database(settings.database_url)
        await app.state.db.open()
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
    db: Database | None = request.app.state.db
    if db is None:
        return _error(
            f"The server is missing {DATABASE_URL_ENV}. Add it to .env.local and restart the agent."
        )
    return await VercelAIAdapter.dispatch_request(
        request,
        agent=request.app.state.agent,
        deps=Deps(db=db),
        sdk_version=SDK_VERSION,
    )


@app.get("/health")
async def health(request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "model": settings.model,
        "database": request.app.state.db is not None,
    }

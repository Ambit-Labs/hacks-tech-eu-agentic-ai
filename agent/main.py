"""The chat agent, served over HTTP.

One Pydantic AI agent with no tools, no memory and no structured output: it
takes the chat messages and streams text back. The Vercel AI adapter speaks the
data-stream protocol the web app's `useChat` already understands, so the
Next.js side only has to point at this server.

`app` is a module-level FastAPI instance because Vercel's Python runtime looks
for that name in `main.py`.
"""

import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from starlette.requests import Request
from starlette.responses import Response

# Kept in step with web/src/lib/model.ts, which picks the same model for the
# TypeScript route.
MODEL_ID = "gemini-3.8-flash"

# GoogleProvider reads GOOGLE_API_KEY on its own. The repo names the key after
# the console it comes from, so the value is passed to the provider explicitly.
API_KEY_ENV = "GOOGLE_AI_STUDIO_KEY"

INSTRUCTIONS = (
    "You are a concise assistant. Answer in short markdown, a few sentences at most."
)

# The web app runs AI SDK 7. The adapter's v7 wire is identical to v6's today,
# but passing the client's real major keeps both ends on the same value.
SDK_VERSION = 7

app = FastAPI()

_agent: Agent | None = None


def get_agent() -> Agent:
    """Builds the agent once. Raises `RuntimeError` when the API key is missing."""
    global _agent

    if _agent is None:
        api_key = os.environ.get(API_KEY_ENV)

        if not api_key:
            raise RuntimeError(f"{API_KEY_ENV} is not set.")

        _agent = Agent(
            GoogleModel(MODEL_ID, provider=GoogleProvider(api_key=api_key)),
            instructions=INSTRUCTIONS,
        )

    return _agent


@app.post("/chat")
async def chat(request: Request) -> Response:
    try:
        agent = get_agent()
    except RuntimeError:
        return JSONResponse(
            {
                "error": (
                    f"The server is missing {API_KEY_ENV}. Add it to .env.local and "
                    "restart the agent."
                )
            },
            status_code=500,
        )

    return await VercelAIAdapter.dispatch_request(request, agent=agent, sdk_version=SDK_VERSION)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "model": MODEL_ID}

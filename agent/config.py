"""Settings read from the environment, once, at startup.

Every name the agent reads from the environment is a constant here, so the
README and the code cannot drift apart.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

MODEL_ENV = "AGENT_MODEL"
# The Pydantic AI Gateway's Vertex route. It needs PYDANTIC_AI_GATEWAY_API_KEY
# in the environment, which Pydantic AI reads for itself.
DEFAULT_MODEL = "gateway/google-cloud:gemini-3.6-flash"

# Only used when AGENT_MODEL names a `google:` model, which the default does
# not. It is the same variable the web app's chat route reads, so one key
# serves both when the agent is pointed straight at AI Studio.
GOOGLE_KEY_ENV = "GOOGLE_AI_STUDIO_KEY"

DATABASE_URL_ENV = "DATABASE_URL"

# The Logfire environment label. `dev` on a laptop, so weekend traces can be
# filtered out later.
ENV_ENV = "AGENT_ENV"
DEFAULT_ENV = "dev"


@dataclass(frozen=True)
class Settings:
    model: str
    # Both secrets: the URL carries the database password. `repr=False` keeps
    # them out of the generated repr, so printing a Settings, logging one, or
    # having Logfire capture a frame that holds one cannot leak them.
    google_api_key: str | None = field(repr=False)
    database_url: str | None = field(repr=False)
    environment: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        return cls(
            model=source.get(MODEL_ENV) or DEFAULT_MODEL,
            google_api_key=source.get(GOOGLE_KEY_ENV) or None,
            database_url=source.get(DATABASE_URL_ENV) or None,
            environment=source.get(ENV_ENV) or DEFAULT_ENV,
        )

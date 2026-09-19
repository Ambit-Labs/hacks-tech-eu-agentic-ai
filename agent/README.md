# Agent

The chat agent behind the web app. One Pydantic AI agent with seven tools
that query the `payments` table in Postgres and stream an answer back in the
Vercel data-stream protocol, which `web/`'s `useChat` reads. The model never
writes SQL; each tool is a fixed, parameterised query.

The data contract is [docs/payments-schema.md](../docs/payments-schema.md).
The design decisions are in
[docs/superpowers/specs/2026-09-19-scrooge-agent-design.md](../docs/superpowers/specs/2026-09-19-scrooge-agent-design.md).

## Run it

From this directory:

```bash
uv run --env-file ../.env.local uvicorn main:app --port 8000
```

`--env-file` is uv's own flag. The file needs `PYDANTIC_AI_GATEWAY_API_KEY`
and `DATABASE_URL`; see the table below. Without `DATABASE_URL` the server
starts and `/chat` answers 500 naming the variable. Without the model key it
does not start.

The gateway key is in place since 2026-09-19, so that command needs nothing in
front of it. When the gateway is unavailable, put
`AGENT_MODEL=google:gemini-3.6-flash` in front of it instead: that calls AI
Studio directly and uses `GOOGLE_AI_STUDIO_KEY`.

`DATABASE_URL` is built from the infra CLI: `cd ../infra && uv run pg url`
gives the superuser URL; replace the user and password with the `agent`
login the loader created. When the Modal container restarts and the address
changes, the agent re-reads it from Modal on the next query, so a restart of
this process is not needed.

## Endpoints

- `POST /chat` runs the agent and streams the reply. The body is what AI
  SDK's `DefaultChatTransport` posts: `id`, `messages`, `trigger`,
  `messageId`.
- `GET /health` returns `{"status": "ok", "model": "...", "database": true}`.

## How the web app reaches it

`next.config.ts` rewrites `/api/agent/:path*` to `${AGENT_URL}/:path*`, so the
browser only ever talks to its own origin and there is no CORS to configure.
`web/src/lib/chat-backend.ts` picks the path the chat transport posts to.

Start this server before the web app, or the chat gets a proxy error on the
first message.

## Tools

| Tool | Answers |
| --- | --- |
| `coverage` | which boroughs and months are loaded |
| `spend_total` | total for one borough and period, with optional department or purpose substring |
| `spend_by` | breakdown by department, purpose, supplier, month or financial year |
| `supplier_payments` | everything paid to a supplier, across boroughs or in one |
| `largest_payments` | biggest single payments |
| `search_payments` | payments matching a word in supplier, purpose or department |
| `compare_boroughs` | several boroughs side by side, per resident when the population is filled |

Every result carries the row count behind it and, when a substring filter
was used, the distinct values it matched.

## Env vars

| Name | Meaning |
| --- | --- |
| `PYDANTIC_AI_GATEWAY_API_KEY` | Pydantic AI Gateway key. Required for the default model, which the gateway routes to Vertex. |
| `PYDANTIC_AI_GATEWAY_BASE_URL` | Optional; the key carries the region, so it can stay unset. When set it must be the proxy root, `https://gateway-eu.pydantic.dev/proxy`. Pydantic AI appends the provider route (`/google-vertex`) itself, so a base URL that already ends in a route name gives 404. |
| `AGENT_MODEL` | Pydantic AI model string. Default `gateway/google-cloud:gemini-3.6-flash`. `gateway/google-cloud:gemini-3.8-flash` works too; both answered through the gateway on 2026-09-19. `gateway/google:` is an alias of `gateway/google-cloud:`. `google:<model>` calls Gemini directly and then needs `GOOGLE_AI_STUDIO_KEY`. `test` gives a fake model for local checks. |
| `GOOGLE_AI_STUDIO_KEY` | Gemini API key. Only when `AGENT_MODEL` starts with `google:`. |
| `DATABASE_URL` | `postgresql://agent:<password>@<host>:<port>/postgres` |
| `LOGFIRE_TOKEN` | Logfire write token for the `hacks-eu-agentic` project. Without it nothing is sent. |
| `AGENT_ENV` | Logfire environment label, default `dev`. |
| `AGENT_URL` (web app) | Where the Next.js rewrite sends `/api/agent/*`. Default `http://127.0.0.1:8000`. |
| `NEXT_PUBLIC_CHAT_BACKEND` (web app) | `ai-sdk` to use the TypeScript route instead. |

## Observability

With `LOGFIRE_TOKEN` set, each request is one trace in Logfire: the HTTP
span, the agent run, every model and tool call with full content, and every
SQL statement. Environment is `AGENT_ENV`.

## Deploy to Vercel

This directory is its own Vercel project. Set Root Directory to `agent` in the
project settings; the web app is a second project with Root Directory `web`.
The Python runtime finds the FastAPI instance through
`[tool.vercel] entrypoint = "main:app"` in `pyproject.toml`, installs from
`[project] dependencies` with `uv.lock` honoured, and takes the Python version
from `.python-version`.

Variables to set on the project:

| Name | Required | Value, or where it comes from |
| --- | --- | --- |
| `PYDANTIC_AI_GATEWAY_API_KEY` | yes | the gateway key, same one as in `.env.local` |
| `PYDANTIC_AI_GATEWAY_BASE_URL` | no | `https://gateway-eu.pydantic.dev/proxy` |
| `AGENT_MODEL` | no | default `gateway/google-cloud:gemini-3.6-flash` |
| `DATABASE_URL` | yes | the `agent` login against the Modal Postgres, the `MODAL_DATABASE_URL` line in `.env.local` |
| `MODAL_TOKEN_ID` | yes | a Modal token for the `ambit-labs` workspace |
| `MODAL_TOKEN_SECRET` | yes | the secret half of that token |
| `LOGFIRE_TOKEN` | no, but wanted | Logfire write token for `hacks-eu-agentic` |
| `AGENT_ENV` | no | set `production`, so deployed traces separate from laptop ones |

The Modal token is what lets the agent re-read the database address after the
Postgres container moves. Without it the first query after a move fails with a
`RuntimeError` naming both variables, and every query after that fails the same
way until the token is set.

`vercel.json` gives the function 120 seconds and pins it to `lhr1`, next to the
London data and the EU gateway. After a deploy, `GET /health` is the check: it
returns the model string and whether the pool was built.

Nothing in the agent is known to break on Vercel. The one difference is that
the coverage summary is cached per function instance, so the first request
after a cold start spends about a second re-reading it.

## Tests

```bash
uv run pytest -q
```

Needs Docker. The session starts one `postgres:17` container, applies
`docs/payments-schema.sql` and `tests/seed.sql`, and removes it at the end.
Set `TEST_DATABASE_URL` to use a database you already have instead; the
schema and seed are applied to it, so make it a disposable one. No test
calls a real model.

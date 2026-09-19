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
| `AGENT_MODEL` | Pydantic AI model string. Default `gateway/google-cloud:gemini-3.6-flash`. `google:<model>` calls Gemini directly and then needs `GOOGLE_AI_STUDIO_KEY`. `test` gives a fake model for local checks. |
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

## Tests

```bash
uv run pytest -q
```

Needs Docker. The session starts one `postgres:17` container, applies
`docs/payments-schema.sql` and `tests/seed.sql`, and removes it at the end.
Set `TEST_DATABASE_URL` to use a database you already have instead; the
schema and seed are applied to it, so make it a disposable one. No test
calls a real model.

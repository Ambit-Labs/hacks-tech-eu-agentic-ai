# Scrooge agent design

Decisions from the 2026-09-19 interview. The data contract is in
[docs/payments-schema.md](../../payments-schema.md); this page is everything
else the agent needs to be built.

## What it is

One Pydantic AI agent behind FastAPI in `agent/`, answering questions about
London borough spending from the `payments` table. The Next.js chat in `web/`
already calls `POST /chat` through the `/api/agent/*` rewrite and renders the
stream, including tool calls as cards. That wiring stays as it is.

## Decisions

1. **One table, typed columns, `raw` for the rest.** See the schema doc. The
   loader session owns the database; the agent only reads it as the
   `scrooge_reader` role through `DATABASE_URL`.
2. **Fixed tools, not text-to-SQL.** The model never writes SQL. Seven tools,
   each a Python function with typed arguments, run parameterised queries.
3. **Tools derived from the user questions.** `coverage`, `spend_total`,
   `spend_by`, `supplier_payments`, `largest_payments`, `search_payments`,
   `compare_boroughs`. Substring filters on department and purpose because
   every borough names them differently; each result reports which distinct
   values the filter matched. `compare_boroughs` supports per-resident figures
   from `boroughs.population` when that column is filled.
4. **Database access.** psycopg 3 async with a small pool. On a connection
   error, re-read host and port from the Modal Dict the infra server
   publishes into (`scrooge-postgres-endpoint`, key `current`), keep the
   user, password and database from `DATABASE_URL`, reopen the pool, retry
   once.
5. **Model.** The model string lives in `AGENT_MODEL`, default
   `google:gemini-3.8-flash` with the key from `GOOGLE_AI_STUDIO_KEY`. The
   Pydantic AI Gateway only routes Google through Vertex today, so the gateway
   is a later config change to `gateway/google-cloud:<model>` once Vertex or a
   custom provider credential exists.
6. **Logfire.** `logfire.configure(service_name="scrooge-agent",
   environment=AGENT_ENV)` with `send_to_logfire="if-token-present"`, then
   `instrument_pydantic_ai(include_content=True)`, `instrument_fastapi(app)`,
   `instrument_psycopg()`. Full message content is sent. No second backend
   yet.
7. **Answers.** Tools return an aggregate, the row count behind it, the
   matched filter values, and at most 50 rows. The model answers in short
   markdown, states borough, period and row count, and says when coverage
   does not include the period asked. Coverage is injected into the
   instructions per request with a dynamic instruction, one cheap query.
8. **No evals this weekend.**
9. **The agent session builds `agent/` only.** No seeding, no DDL. Another
   session loads the data.
10. **Tests.** pytest against a Postgres 17 Docker container with the schema
    applied and a hand-written seed. Agent tests use `FunctionModel` and
    `TestModel`, no real LLM. One manual end-to-end run against Modal once
    data lands.

## Code layout

```
agent/
  main.py            FastAPI app, lifespan, /chat and /health
  config.py          Settings read from the environment
  observability.py   Logfire setup
  db.py              Database pool and the Modal re-resolve
  tools.py           Deps, result models, the seven tools
  agent.py           build_model, build_agent, instructions
  tests/
    conftest.py      Docker Postgres fixture, schema and seed applied
    seed.sql         two boroughs, two months, ~20 payments
    test_db.py  test_tools.py  test_agent.py  test_main.py
```

## Environment variables

| Name | Where | Meaning |
| --- | --- | --- |
| `GOOGLE_AI_STUDIO_KEY` | agent | Gemini API key, required when `AGENT_MODEL` starts with `google:` |
| `AGENT_MODEL` | agent | Pydantic AI model string, default `google:gemini-3.8-flash` |
| `DATABASE_URL` | agent | `postgresql://agent:<password>@<host>:<port>/postgres` |
| `LOGFIRE_TOKEN` | agent | Logfire write token; without it nothing is sent |
| `AGENT_ENV` | agent | `dev` by default; the Logfire environment label |
| `PYDANTIC_AI_GATEWAY_API_KEY` | agent | only when `AGENT_MODEL` starts with `gateway/` |
| `AGENT_URL` | web | where the rewrite sends `/api/agent/*` |
| `NEXT_PUBLIC_CHAT_BACKEND` | web | `ai-sdk` to use the TypeScript route instead |

# Scrooge

Where did the money go?

London's 33 boroughs each publish every payment over £500 (over £250 in some)
under the transparency code, as CSVs in 33 different shapes on 33 different
websites. Scrooge collects them, loads them into one Postgres, and puts a chat
agent in front so you can ask the question in the title and get an answer with
the rows behind it.

Built at the hacks.tech.eu agentic AI hackathon, 2026-09-19.

## How it fits together

```
borough websites ──▶ indexer/  scrooge download: raw files on disk, one manifest per borough
                         │
                         │     scrooge load: 33 column layouts become one payments table
                         ▼
                     infra/    Postgres 17 on Modal, the pg CLI
                         │
                         │     seven fixed SQL tools, SELECT only
                         ▼
                     agent/    Pydantic AI + FastAPI, streams answers and tool results
                         │
                         ▼
                     web/      Next.js chat UI, draws each tool result as a table or chart
```

[docs/architecture.md](docs/architecture.md) has the full picture: diagrams of
the ingest pipeline, the schema, the Modal server's lifecycle, one question
traced end to end, and the deployment.

| Directory | What it is | Stack | Docs |
| --- | --- | --- | --- |
| `indexer/` | Downloads each borough's spending and budget files byte for byte and keeps a manifest. One source is one Python file. `scrooge load` then parses the spend files into Postgres. | Python 3.12, uv, httpx, psycopg, argparse, rich | [README](indexer/README.md), [runbook](indexer/docs/runbook.md) |
| `infra/` | Postgres 17 as a real server process in a Modal container, reached through a Modal TCP tunnel. Dumps to a Volume, restores on boot. | Python, Modal | [README](infra/README.md), [runbook](infra/docs/runbook.md) |
| `agent/` | The chat agent. Takes AI SDK messages, answers from seven read-only SQL tools over the `payments` table, streams text and tool results back in the AI SDK stream protocol. Traced with Logfire. | Pydantic AI, FastAPI, psycopg, Gemini through the Pydantic AI Gateway | [README](agent/README.md), [design](docs/superpowers/specs/2026-09-19-scrooge-agent-design.md) |
| `web/` | The chat UI. Proxies `/api/agent/*` to the agent so the browser only talks to its own origin, and renders each tool result as a card with a table or a bar chart. | Next.js 16, Bun, AI SDK 7, shadcn, AI Elements, Recharts | [README](web/README.md) |
| `docs/` | The architecture doc, the payments schema, and research notes: where each borough publishes, which ones block bots, budget sources, and a framework comparison. | Markdown, SQL, JSON | [architecture](docs/architecture.md), [payments schema](docs/payments-schema.md), [research](docs/research), [Pydantic AI vs eve and Mastra](docs/pydantic-ai-vs-eve-mastra.md) |
| `data/` | Downloaded files and manifests. Gitignored. | | |

## Quick start

Each directory is its own project. Python parts use [uv](https://docs.astral.sh/uv/),
the web app uses [Bun](https://bun.sh).

Download spending files for one borough:

```sh
cd indexer && uv sync
uv run scrooge list
uv run scrooge download camden
uv run scrooge status
```

Bring up the database (needs a Modal account and the secret described in the
[infra runbook](infra/docs/runbook.md#cold-start)):

```sh
cd infra && uv sync
uv run pg deploy      # once, and after any change to postgres_app.py
uv run pg start
export DATABASE_URL="$(uv run pg url)"
uv run pg stop        # when done, it bills while up
```

Load what you downloaded. `DATABASE_URL` has to be a login that can write:

```sh
cd indexer
uv run scrooge db init                # schema once, then the 33 boroughs
uv run scrooge load camden
uv run scrooge load-status --problems # what loaded, what did not and why
```

Run the chat. Put `PYDANTIC_AI_GATEWAY_API_KEY` and a `DATABASE_URL` for the
read-only `agent` login in `.env.local` at the repo root, then start the agent
before the web app. `LOGFIRE_TOKEN` in the same file turns tracing on. The
[agent README](agent/README.md) lists every variable, including how to skip the
gateway with a `google:` model and `GOOGLE_AI_STUDIO_KEY`.

```sh
cd agent && uv sync
uv run --env-file ../.env.local uvicorn main:app --port 8000
curl -s localhost:8000/health         # model string, and whether the database is set
```

```sh
cd web && bun install
bun run dev           # http://127.0.0.1:3020
```

## Status

- 15 boroughs download today: Barnet, Bexley, Brent, Camden, Haringey,
  Havering, Hounslow, Islington, Lambeth, Lewisham, Newham, Redbridge,
  Richmond, Wandsworth, Westminster.
- 5 boroughs sit behind bot protection and are left alone. The remaining 13
  are researched but not yet written. Details in
  [docs/research/london-borough-spending](docs/research/london-borough-spending).
- 12 budget sources download too: MHCLG returns for all 33 boroughs, the London
  Datastore council tax set, and ten borough budget books. Nothing loads them
  into Postgres yet, so the agent cannot set spend against budget.
- The agent answers from Postgres through seven tools: `coverage`,
  `spend_total`, `spend_by`, `supplier_payments`, `largest_payments`,
  `search_payments` and `compare_boroughs`. The model never writes SQL, every
  row-returning tool stops at 50 rows, and a run stops after 12 model requests.
- The web app draws each tool result as a card. The raw tool calls sit behind a
  "Show tool calls" switch in the header.
- `web/` and `agent/` are set up as two Vercel projects from this repo. The
  agent runs in `lhr1` with a 120 second limit.
- The agent has no authentication of its own. Keep its URL private.
- Open work is on the [issue tracker](../../issues). The two data bugs to know
  about are Redbridge rows dated up to 2036 (#11) and "Capita" matching every
  "capital" (#10).

## Tests

```sh
cd indexer && uv run pytest -q   # 355 tests, no network or database needed
cd infra && uv run pytest -q     # 45 tests, Modal is never called
cd agent && uv run pytest -q     # needs Docker, starts a throwaway postgres:17
cd web && bun run lint && bun run format:check
```

The three Python projects share one ruff config, in each `pyproject.toml`.
Run it per project:

```sh
cd agent && uv run ruff check . && uv run ruff format --check .
```

The indexer's loader tests against a real database skip themselves unless
`SCROOGE_TEST_DATABASE_URL` is set. No test calls a real model.

## Conventions

- Long-running commands show a rich progress bar on stderr and fall back to
  plain lines when piped.
- Every CLI change lands in that project's runbook in the same commit.
- The domain word is "spend". The project is Scrooge. Package, CLI, env var
  and Modal names carry `scrooge`; the data and the sources keep their own
  names.

## License

[MIT](LICENSE.md).

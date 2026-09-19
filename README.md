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
borough websites ──▶ indexer/  (scrooge CLI, raw CSVs on disk, one file per borough)
                         │
                         ▼
                     infra/    (Postgres 17 on Modal, the pg CLI)
                         │
                         ▼
                     agent/    (Pydantic AI + FastAPI, streams answers)
                         │
                         ▼
                     web/      (Next.js chat UI)
```

| Directory | What it is | Stack | Docs |
| --- | --- | --- | --- |
| `indexer/` | Downloads each borough's spending files byte for byte and keeps a manifest. One borough is one Python file. | Python 3.12, uv, argparse, rich | [README](indexer/README.md), [runbook](indexer/docs/runbook.md) |
| `infra/` | Postgres 17 as a real server process in a Modal container, reached through a Modal TCP tunnel. Dumps to a Volume, restores on boot. | Python, Modal | [README](infra/README.md), [runbook](infra/docs/runbook.md) |
| `agent/` | The chat agent. Takes AI SDK messages, streams text back in the Vercel data-stream protocol. | Pydantic AI, FastAPI, Gemini via Google AI Studio | [README](agent/README.md) |
| `web/` | The chat UI. Proxies `/api/agent/*` to the agent so the browser only talks to its own origin. | Next.js 16, Bun, shadcn, AI Elements | [README](web/README.md) |
| `docs/` | Research notes: where each borough publishes, which ones block bots, budget sources, and a framework comparison. | Markdown, JSON | [research](docs/research), [Pydantic AI vs eve and Mastra](docs/pydantic-ai-vs-eve-mastra.md) |
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

Run the chat. Put `GOOGLE_AI_STUDIO_KEY` in `web/.env.local`, then start the
agent before the web app:

```sh
cd agent && uv sync
uv run --env-file ../web/.env.local uvicorn main:app --port 8000
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
- The agent answers from the model alone for now. Wiring it to the Postgres
  rows is the next step.

## Conventions

- Long-running commands show a rich progress bar on stderr and fall back to
  plain lines when piped.
- Every CLI change lands in that project's runbook in the same commit.
- The domain word is "spend". The project is Scrooge. Package, CLI, env var
  and Modal names carry `scrooge`; the data and the sources keep their own
  names.

## License

[MIT](LICENSE.md).

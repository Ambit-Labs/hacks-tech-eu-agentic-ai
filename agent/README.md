# Agent

A single Pydantic AI agent behind FastAPI. No tools, no memory, no structured
output: it takes the chat messages and streams text back. The Vercel AI adapter
writes the data-stream protocol that the web app's `useChat` already reads, so
the chat UI needs nothing beyond a URL.

## Run it

From this directory:

```bash
uv run --env-file ../.env.local uvicorn main:app --port 8000
```

`--env-file` is uv's own flag, so nothing extra has to be installed to load the
key. Point it at `../web/.env.local` instead if that is where your key lives.

## Endpoints

- `POST /chat` runs the agent and streams the reply as server-sent events. The
  request body is what AI SDK's `DefaultChatTransport` posts: `id`, `messages`,
  `trigger`, `messageId`.
- `GET /health` returns `{"status": "ok", "model": "..."}`.

## Env vars

- `GOOGLE_AI_STUDIO_KEY` (this server): the Google AI Studio key. Without it
  `POST /chat` answers 500 with a message naming the variable. The name matches
  `web/src/lib/model.ts`, so the two backends share one key.
- `AGENT_URL` (web app): where the Next.js rewrite sends `/api/agent/*`.
  Defaults to `http://127.0.0.1:8000`.
- `NEXT_PUBLIC_CHAT_BACKEND` (web app): set it to `ai-sdk` to point the chat at
  the TypeScript route instead. Anything else, or unset, uses this agent.

## How the web app reaches it

`next.config.ts` rewrites `/api/agent/:path*` to `${AGENT_URL}/:path*`, so the
browser only ever talks to its own origin and there is no CORS to configure.
`web/src/lib/chat-backend.ts` picks the path the chat transport posts to.

Start this server before the web app, or the chat gets a proxy error on the
first message.

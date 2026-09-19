This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
bun run dev
```

The dev server listens on `127.0.0.1:3020` only. On the devsicap box Caddy serves it over https on the tailnet name, so from another machine open [https://devsicap:3020](https://devsicap:3020) (MagicDNS, works on any tailnet device) or [https://devsicap.ts.sicap.ai:3020](https://devsicap.ts.sicap.ai:3020) (public DNS, blocked by routers with rebind protection). On the box itself use [http://127.0.0.1:3020](http://127.0.0.1:3020).

The Caddy site block lives in `scripts/dev/Caddyfile.devsicap`, with the one-time install commands in its header. The certificate comes from Caddy's internal CA, so the machine opening the browser must trust Caddy's `root.crt`. `allowedDevOrigins` in `next.config.ts` lets HMR work from that hostname. The chat route needs `GOOGLE_AI_STUDIO_KEY` in `web/.env.local`.

## Chat backend

The chat posts to the Pydantic AI agent in `agent/` by default, proxied by the `/api/agent/:path*` rewrite in `next.config.ts`. Start that server too, see `agent/README.md`. Two env vars steer it:

- `AGENT_URL` — where the rewrite sends `/api/agent/*`. Defaults to `http://127.0.0.1:8000`.
- `NEXT_PUBLIC_CHAT_BACKEND` — set it to `ai-sdk` to use the TypeScript route at `src/app/api/chat/route.ts` instead. It is inlined at build time, so changing it needs a restart.

## Result components

Each of the agent's tools is drawn by a component of its own, in `src/components/chat/results/`. `ToolResult` picks one by tool name and is the only thing the conversation renders for a tool call: the component when the result is in, a one-line shimmer while the call runs, a short line when it fails.

| Tool                                  | Component                                                                               |
| ------------------------------------- | --------------------------------------------------------------------------------------- |
| `coverage`                            | `coverage.tsx`, a shaded month strip per borough                                        |
| `spend_total`                         | `spend-total.tsx`, the total, the count and the average payment                         |
| `spend_by`                            | `spend-by.tsx`, a bar chart and a table, horizontal for a ranking and columns over time |
| `largest_payments`, `search_payments` | `payments.tsx`, the totals over the whole set and the rows returned                     |
| `supplier_payments`                   | `supplier-payments.tsx`, the same rows under a supplier header                          |
| `compare_boroughs`                    | `borough-comparison.tsx`, bars with a toggle for spend per resident                     |

The adapter puts a tool call on the wire as a part typed `tool-<name>` and never marks it dynamic, so `getToolName` from the AI SDK gives the name on the client.

Tool output is validated before it is drawn. `src/lib/agent-results.ts` holds one zod schema per result type, mirroring the Pydantic models in `agent/tools.py` field for field. A result that does not parse shows one muted line rather than taking the conversation down. Money, dates and borough slugs are formatted in `src/lib/format.ts`, and charts are the shadcn `chart` wrapper over Recharts, coloured from the `--chart-*` variables in `globals.css`.

To add a component for a new tool: mirror its Pydantic model as a schema in `agent-results.ts` and register it in `RESULT_SCHEMAS` under the tool's name, write the component beside the others, add a case to the switch in `results/index.tsx`, and give the tool a line in `RUNNING` so the shimmer says what the call is doing. A tool with no component renders nothing.

## Settings

The gear in the header carries two settings, both kept in `localStorage` by the small store in `src/lib/settings.ts`.

"Show tool calls" is off by default. Turned on, the raw card for every call, its name, its arguments and the JSON it returned, renders under the result component, collapsed. The value is kept in `localStorage` under `scrooge:show-tool-calls` and read with `useSyncExternalStore` whose server snapshot is `false`, so the first client render matches the server HTML and there is no hydration mismatch.

"Theme" is Light, Dark or System, and Light is the default: a first visit gets the light palette even on a dark OS. The choice is stored under `scrooge:theme` and lands on `<html>` as `class="light"`, `class="dark"` or neither, which is what the token blocks in `globals.css` key off. "System" is the no-class case and follows `prefers-color-scheme`. The root layout ships `class="light"` and an inline script in `<head>`, from `src/lib/theme.ts`, swaps it for the stored choice before the first paint, so a reload in dark never flashes light. `<html>` has `suppressHydrationWarning` for that reason. A change in one tab reaches the others through the `storage` event.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

This directory is its own Vercel project. Set Root Directory to `web` in the
project settings; the agent is a second project with Root Directory `agent`.

Variables to set on the project:

| Name                       | Required           | Value, or where it comes from                                                    |
| -------------------------- | ------------------ | -------------------------------------------------------------------------------- |
| `AGENT_URL`                | yes                | the agent project's URL, `https://<agent-project>.vercel.app`, no trailing slash |
| `NEXT_PUBLIC_CHAT_BACKEND` | no                 | `ai-sdk` to post to the TypeScript route instead of the agent                    |
| `GOOGLE_AI_STUDIO_KEY`     | only with `ai-sdk` | Gemini API key, the same one `web/.env.local` holds                              |

`next.config.ts` reads `AGENT_URL` while the config is evaluated, which happens
at build time, so it has to be set before the build and a change to it needs a
redeploy, not just a restart. `NEXT_PUBLIC_CHAT_BACKEND` is inlined into the
client bundle for the same reason.

Because the browser reaches the agent through the `/api/agent/:path*` rewrite,
both deployments stay on one origin and there is still no CORS to configure.

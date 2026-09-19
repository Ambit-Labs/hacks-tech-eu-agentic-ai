# Pydantic AI vs eve and Mastra

As of 2026-09-19.

## Summary

Pydantic AI beats eve and Mastra in three places. You choose where the agent survives a crash, the traces go to any backend, and Logfire covers the whole app. The cost is that it ships much less in the box.

It is a Python library with no runtime. eve and Mastra are TypeScript, so switching languages is the biggest tradeoff.

"Pydantic" here means five separate packages:

- [Pydantic AI](https://pydantic.dev/docs/ai/core-concepts/agent/) is the agent library, at version 2.46.0 on [PyPI](https://pypi.org/project/pydantic-ai/).
- [pydantic-ai-harness](https://pydantic.dev/docs/ai/harness/) adds memory, subagents and guardrails, at version 0.32.0.
- [Pydantic Evals](https://pydantic.dev/docs/ai/evals/evals/) runs evaluations.
- [Logfire](https://pydantic.dev/docs/logfire/integrations/) is the observability service.
- The [Pydantic AI Gateway](https://pydantic.dev/docs/ai/overview/gateway/) routes model calls to the providers.

## How it maps to what you know

Most eve and Mastra concepts have a Pydantic equivalent, but half of them live outside the stable core.

| You know | Pydantic equivalent | The catch |
| --- | --- | --- |
| [eve](https://eve.dev/docs/agent-config)'s agent directory, [Mastra](https://mastra.ai/docs/agents/overview)'s `new Agent()` | `Agent(model, deps_type, output_type, tools)` | No project layout and nothing to run the agent on. |
| Zod schemas | Pydantic models. A failed validation goes back to the model as a retry. | Roughly equal to Zod. |
| eve durable sessions, Mastra suspend and resume | `capabilities=[DBOSDurability()]`, or Temporal, Prefect, Restate, AWS Lambda | You choose it and run it yourself. eve does this with no setup. |
| Mastra memory and RAG, eve memory providers | Not in the core library. The harness has Memory, Skills, Subagents, Compaction, Guardrails and about 50 more. | The harness is 0.x, and its docs say APIs can change between minor releases. |
| Mastra Studio, eve dev TUI | `clai web` or `agent.to_web()` | The docs call these development-only chat UIs. Logfire is where you read traces. |
| eve channels, schedules, sandboxes | None built in | You write them yourself. |
| Vercel Agent Runs, Langfuse | Logfire | The Logfire server is closed source. |
| AI SDK frontend | [`VercelAIAdapter`](https://pydantic.dev/docs/ai/integrations/ui/vercel-ai/) speaks the AI SDK stream protocol | Your Next.js chat UI can stay. |

## Where it is better

The wins are choice of crash recovery, portable traces, and an observability service that sees more than LLM calls.

- **Crash recovery is your choice.** [DBOS](https://pydantic.dev/docs/ai/integrations/durable_execution/dbos/) runs inside your process and saves progress to SQLite in development and Postgres in production, with no extra server. [Temporal](https://pydantic.dev/docs/ai/integrations/durable_execution/overview/) fits if you already run it. eve's default ties you to Vercel Workflow, and Mastra's default storage is in memory.
- **Traces go wherever you want.** The instrumentation is plain OpenTelemetry using the GenAI conventions. [Langfuse](https://langfuse.com/integrations/frameworks/pydantic-ai) and [PostHog](https://posthog.com/docs/llm-analytics/installation/pydantic-ai) both take the traces after `Agent.instrument_all()`.
- **Logfire covers the whole app.** It traces FastAPI, the database and HTTP calls alongside agent runs, and you query it with [SQL](https://pydantic.dev/docs/logfire/reference/sql/). Langfuse only sees the LLM calls.
- **Logfire's free tier is large.** It allows 10M records a month, against 50k units on Langfuse and 100k events on PostHog. You pick the [EU or US region](https://pydantic.dev/docs/logfire/manage/data-regions/) at signup and cannot move later.
- **Evals are code.** `pydantic-evals` runs datasets, custom checks and an LLM judge from your code. The results [show up in Logfire](https://pydantic.dev/docs/ai/evals/how-to/logfire-integration/) automatically.
- **Human approval is built in.** A tool can set `requires_approval=True`, and the run pauses with a list of [tool calls waiting for approval](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/).

## Where it is worse

You host it yourself, and the parts eve and Mastra ship by default sit in a 0.x package or do not exist.

- **You host it yourself.** That usually means FastAPI plus your own deployment. There is no `vercel deploy` for agents and no hosted cloud.
- **The harness may change under you.** Memory, subagents and the rest live in the 0.x [harness package](https://pydantic.dev/docs/ai/harness/) rather than the stable core.
- **Releases are fast.** Pydantic AI 2.46.0 went out on 2026-09-19, and [releases](https://github.com/pydantic/pydantic-ai/releases) land every day or two. Pin exact versions.
- **Much online material is out of date.** Version 2 shipped in June 2026 and deprecated the older wrappers such as `DBOSAgent`. The [version policy](https://pydantic.dev/docs/ai/project/version-policy/) keeps deprecated APIs until the next major.
- **Streaming is limited under durable execution.** The DBOS docs describe buffered delivery, and cancelling a run from the workflow side is not available.
- **No store for conversation history.** You save the messages yourself. The request for one has been open since December 2024 ([#530](https://github.com/pydantic/pydantic-ai/issues/530)).
- **Smaller providers are reported as flaky.** GitHub issues describe streaming and structured output problems on Azure, vLLM and Ollama ([#748](https://github.com/pydantic/pydantic-ai/issues/748)). This is community opinion, not something tested here.

Two facts about eve and Mastra came up. [eve](https://github.com/vercel/eve) is a three-month-old public beta. [Mastra](https://github.com/mastra-ai/mastra)'s `ee/` directory, which covers auth and the editor, needs a paid license for production use.

## Observability compared

Logfire wins on scope and free volume, Langfuse on prompt work and self-hosting, PostHog on tying traces to users.

| | [Logfire](https://pydantic.dev/pricing) | [Langfuse](https://langfuse.com/pricing) | [PostHog](https://posthog.com/docs/llm-analytics) |
| --- | --- | --- | --- |
| Scope | Whole app over OpenTelemetry | LLM calls only | Product analytics suite, LLM analytics is one module |
| Pydantic AI setup | `logfire.configure()` plus `logfire.instrument_pydantic_ai()` | Env vars, then `Agent.instrument_all()` | `PostHogSpanProcessor` on a `TracerProvider`, then `Agent.instrument_all()` |
| Sessions and users | No built-in session or user object | Sessions group traces, user id on the trace | Traces attach to PostHog persons and sessions |
| Prompt management | Versioned prompts with labels | Versions, labels, playground with variant comparison | Versions, labels, playground |
| Human review | Annotation queues for design partners only, no documented scores API | Annotation queues and a scores API | Review queues with scorers |
| Querying | SQL, SQL-backed dashboards and alerts | REST metrics API, no raw SQL | HogQL, PostHog's SQL dialect |
| Product analytics link | None | None | Session replay, feature flags, prompt experiments |
| Self-hosting | Enterprise plan only, server closed source | MIT core, tracing, prompts and evals free | MIT except `ee/`, no support when self-hosted |
| Free tier per month | 10M records, 30-day retention | 50k units, 30-day retention | 100k events |
| First paid tier | $49 a month, then $2 per million records | $29 a month, then $8 per 100k units | Per event, from $0.00035 |
| EU region | Yes, fixed at signup | Yes, Ireland | Yes, Frankfurt |

You do not have to pick one backend up front. [Langfuse](https://langfuse.com/faq/all/existing-otel-setup) documents running its span processor next to another exporter. [Logfire](https://pydantic.dev/docs/logfire/get-started/faq/) documents sending the same traces to two backends through an OpenTelemetry Collector. PostHog documents no dual setup.

## Recommended starting stack

Start with Pydantic AI and Logfire's free tier in the EU region. Setup is `logfire.configure()` plus `logfire.instrument_pydantic_ai()`.

- Add `DBOSDurability` once runs get long enough that a crash would hurt.
- Add PostHog's `PostHogSpanProcessor` when real users arrive and you want replays tied to traces.
- Choose Langfuse instead of Logfire if self-hosting or reviewed prompt versions are requirements.
- Pin exact versions of `pydantic-ai` and `pydantic-ai-harness` from the first commit.

## Sources and what was checked

Five pages were reopened directly on 2026-09-19. Everything else comes from three research agents' reports and was not rechecked.

Rechecked directly:

- [PyPI](https://pypi.org/project/pydantic-ai/) for the versions of `pydantic-ai`, `pydantic-ai-harness`, `pydantic-evals` and `logfire`
- [Logfire pricing](https://pydantic.dev/pricing), including self-hosting on Enterprise only and the gateway markup
- [DBOS durable execution](https://pydantic.dev/docs/ai/integrations/durable_execution/dbos/), including `DBOSDurability`, the deprecated `DBOSAgent` and the streaming limits
- [Pydantic AI Harness](https://pydantic.dev/docs/ai/harness/), including the 0.x versioning note and the capability list
- [PostHog's Pydantic AI setup](https://posthog.com/docs/llm-analytics/installation/pydantic-ai)

From the agents' reports, not rechecked:

- The [Langfuse Pydantic AI integration](https://langfuse.com/integrations/frameworks/pydantic-ai), Langfuse pricing, prompt management and evals
- All [eve](https://eve.dev/docs/concepts/execution-model-and-durability) and [Mastra](https://mastra.ai/docs/server-db/storage) facts, including Mastra's `ee/` license
- PostHog pricing, HogQL and the session replay link
- The community complaints, which are opinion from GitHub issues and Hacker News

Still unconfirmed:

- Whether the Pydantic AI Gateway is generally available. A November 2025 post called it open beta, and the pricing page now shows fees with no beta label.
- Whether self-hosted PostHog has the full LLM analytics module.
- Mastra's full list of trace exporters and built-in scorers. One docs page returned a 404.

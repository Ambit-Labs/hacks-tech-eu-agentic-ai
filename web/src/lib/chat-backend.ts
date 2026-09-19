/**
 * Which backend the chat talks to.
 *
 * The default is the Pydantic AI agent, proxied by the rewrite in
 * `next.config.ts`. Set `NEXT_PUBLIC_CHAT_BACKEND=ai-sdk` to use the
 * TypeScript route in `src/app/api/chat/route.ts` instead. The value is
 * inlined at build time, so a change needs a restart.
 */
export const CHAT_API_PATH =
  process.env.NEXT_PUBLIC_CHAT_BACKEND === "ai-sdk" ? "/api/chat" : "/api/agent/chat";

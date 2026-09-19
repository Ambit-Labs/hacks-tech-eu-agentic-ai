import {
  convertToModelMessages,
  createUIMessageStreamResponse,
  isStepCount,
  streamText,
  toUIMessageStream,
  type UIMessage,
} from "ai";

import { chatTools } from "@/lib/chat-tools";
import {
  CHAT_MODEL_API_KEY_ENV,
  CHAT_MODEL_PROVIDER_OPTIONS,
  getChatModel,
  isChatModelConfigured,
} from "@/lib/model";

export const maxDuration = 30;

const MAX_STEPS = 5;

const SYSTEM_PROMPT = [
  "You are a concise assistant with a few tools.",
  "Call a tool whenever it can answer part of the question: calculate for any arithmetic,",
  "getCurrentTime for the time anywhere, rollDice for random rolls. Never do arithmetic in your head.",
  "Answer in short markdown. State the numbers the tools returned.",
].join(" ");

function errorResponse(message: string, status: number) {
  return Response.json({ error: message }, { status });
}

export async function POST(req: Request) {
  if (!isChatModelConfigured()) {
    return errorResponse(
      `The server is missing ${CHAT_MODEL_API_KEY_ENV}. Add it to web/.env.local and restart the dev server.`,
      500,
    );
  }

  let messages: UIMessage[];

  try {
    const body: unknown = await req.json();
    const candidate = (body as { messages?: unknown } | null)?.messages;

    if (!Array.isArray(candidate)) {
      return errorResponse('Request body must be JSON with a "messages" array.', 400);
    }

    messages = candidate as UIMessage[];
  } catch {
    return errorResponse("Request body must be valid JSON.", 400);
  }

  const result = streamText({
    model: getChatModel(),
    system: SYSTEM_PROMPT,
    messages: await convertToModelMessages(messages),
    tools: chatTools,
    stopWhen: isStepCount(MAX_STEPS),
    providerOptions: CHAT_MODEL_PROVIDER_OPTIONS,
  });

  return createUIMessageStreamResponse({
    stream: toUIMessageStream({
      stream: result.stream,
      sendReasoning: true,
    }),
  });
}

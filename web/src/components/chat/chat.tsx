"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport, isToolUIPart } from "ai";
import Image from "next/image";
import { Fragment, useCallback, useMemo } from "react";

import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { Message, MessageContent, MessageResponse } from "@/components/ai-elements/message";
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  type PromptInputMessage,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
} from "@/components/ai-elements/prompt-input";
import { Reasoning, ReasoningContent, ReasoningTrigger } from "@/components/ai-elements/reasoning";
import { Suggestion } from "@/components/ai-elements/suggestion";
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
  type ToolPart,
} from "@/components/ai-elements/tool";
import { ToolResult } from "@/components/chat/results";
import { WorkingLine } from "@/components/chat/working";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { CHAT_API_PATH } from "@/lib/chat-backend";
import { useShowToolCalls } from "@/lib/settings";

const SUGGESTIONS = [
  "Who got the most money from Camden in 2024?",
  "What did Richmond pay Achieving for Children in 2023?",
  "Which spent more per resident in 2025: Richmond, Camden or Islington?",
  "How has Islington's spending changed year by year since 2020?",
];

/** One tool call: name, status badge, the input it was given and what it returned. */
function ToolCard({ part }: { part: ToolPart }) {
  return (
    // The result above it is the answer, so the raw call starts collapsed.
    <Tool defaultOpen={false}>
      {part.type === "dynamic-tool" ? (
        <ToolHeader state={part.state} toolName={part.toolName} type={part.type} />
      ) : (
        <ToolHeader state={part.state} type={part.type} />
      )}
      <ToolContent>
        {/* The input arrives token by token, so it is undefined on the first render.
            ToolInput feeds it straight to a code block, which throws on undefined. */}
        {part.input === undefined ? null : <ToolInput input={part.input} />}
        <ToolOutput errorText={part.errorText} output={part.output} />
      </ToolContent>
    </Tool>
  );
}

export function Chat() {
  const showToolCalls = useShowToolCalls();
  const transport = useMemo(() => new DefaultChatTransport({ api: CHAT_API_PATH }), []);
  const { messages, sendMessage, status, error, regenerate, clearError, stop } = useChat({
    transport,
  });

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) {
        return;
      }
      if (error) {
        clearError();
      }
      sendMessage({ text: trimmed });
    },
    [clearError, error, sendMessage],
  );

  const handleSubmit = useCallback(
    (message: PromptInputMessage) => {
      send(message.text);
    },
    [send],
  );

  const handleRetry = useCallback(() => {
    clearError();
    regenerate();
  }, [clearError, regenerate]);

  const isEmpty = messages.length === 0;

  return (
    <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col gap-3 px-3 pb-4 sm:px-6">
      <Conversation className="min-h-0">
        <ConversationContent className={isEmpty ? "h-full gap-6" : "gap-6"}>
          {isEmpty ? (
            // Children replace the component's own icon, title and description
            // layout, which has no slot for the suggestions.
            <ConversationEmptyState className="px-0">
              {/* Decorative: the title under it says what the page is for. */}
              <Image
                alt=""
                className="h-auto w-56"
                height={1086}
                priority
                sizes="224px"
                src="/scrooge-investigating.png"
                width={1448}
              />
              <div className="space-y-1">
                <h3 className="font-medium text-sm">Where did the money go?</h3>
                <p className="mx-auto max-w-xl text-muted-foreground text-sm">
                  Find out what your council tax money is spent on.
                </p>
              </div>
              {/* A wrapping row, not the scrolling <Suggestions> strip: centred
                  under the text, a clipped last pill reads as a bug. */}
              <div className="mt-2 flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((suggestion) => (
                  <Suggestion key={suggestion} onClick={send} suggestion={suggestion} />
                ))}
              </div>
            </ConversationEmptyState>
          ) : null}

          {messages.map((message) => (
            <Message from={message.role} key={message.id}>
              <MessageContent className={message.role === "assistant" ? "w-full" : undefined}>
                {message.parts.map((part, index) => {
                  const key = `${message.id}-${index}`;

                  if (part.type === "text") {
                    return <MessageResponse key={key}>{part.text}</MessageResponse>;
                  }

                  if (part.type === "reasoning") {
                    return (
                      <Reasoning isStreaming={part.state === "streaming"} key={key}>
                        <ReasoningTrigger />
                        <ReasoningContent>{part.text}</ReasoningContent>
                      </Reasoning>
                    );
                  }

                  if (isToolUIPart(part)) {
                    return (
                      <Fragment key={key}>
                        <ToolResult part={part} />
                        {showToolCalls ? <ToolCard part={part} /> : null}
                      </Fragment>
                    );
                  }

                  return null;
                })}
              </MessageContent>
            </Message>
          ))}

          {status === "submitted" ? (
            <Message from="assistant">
              <MessageContent>
                <WorkingLine />
              </MessageContent>
            </Message>
          ) : null}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>The request failed</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            <span>Something went wrong on the way to the model. Try again.</span>
            <Button onClick={handleRetry} size="sm" variant="outline">
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      <PromptInput onSubmit={handleSubmit}>
        <PromptInputBody>
          {/* Password managers (Dashlane, 1Password) stamp data-* attributes on
              form fields before React hydrates. Those attributes are the only
              mismatch, so the warning is noise on the field and the button. */}
          <PromptInputTextarea
            placeholder="Ask about a borough's spend, a supplier or a period"
            suppressHydrationWarning
          />
        </PromptInputBody>
        <PromptInputFooter>
          <PromptInputTools>
            <span className="hidden text-muted-foreground text-xs sm:inline">
              Enter sends, Shift+Enter adds a line
            </span>
          </PromptInputTools>
          <PromptInputSubmit onStop={stop} status={status} suppressHydrationWarning />
        </PromptInputFooter>
      </PromptInput>
    </div>
  );
}

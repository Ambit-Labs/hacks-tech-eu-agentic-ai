"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport, isToolUIPart } from "ai";
import { WrenchIcon } from "lucide-react";
import { useCallback, useMemo } from "react";

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
import { Shimmer } from "@/components/ai-elements/shimmer";
import { Suggestion, Suggestions } from "@/components/ai-elements/suggestion";
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
  type ToolPart,
} from "@/components/ai-elements/tool";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { CHAT_API_PATH } from "@/lib/chat-backend";

const SUGGESTIONS = [
  "What is 17 * 23, and the time in Bucharest?",
  "Roll 3 six-sided dice",
  "(1200 / 16) ^ 2 - 45",
];

/** One tool call: name, status badge, the input it was given and what it returned. */
function ToolCard({ part }: { part: ToolPart }) {
  return (
    <Tool defaultOpen={part.state !== "output-available"}>
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
            <ConversationEmptyState
              description="Ask for arithmetic, the time somewhere, or a dice roll. The answer comes back with the tool calls that produced it."
              icon={<WrenchIcon className="size-6" />}
              title="Three tools, one loop"
            />
          ) : null}

          {messages.map((message) => (
            <Message from={message.role} key={message.id}>
              <MessageContent>
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
                    return <ToolCard key={key} part={part} />;
                  }

                  return null;
                })}
              </MessageContent>
            </Message>
          ))}

          {status === "submitted" ? (
            <Message from="assistant">
              <MessageContent>
                <Shimmer>Working on it</Shimmer>
              </MessageContent>
            </Message>
          ) : null}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      {isEmpty ? (
        <Suggestions>
          {SUGGESTIONS.map((suggestion) => (
            <Suggestion key={suggestion} onClick={send} suggestion={suggestion} />
          ))}
        </Suggestions>
      ) : null}

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
            placeholder="Ask for a calculation, a time zone, or a dice roll"
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

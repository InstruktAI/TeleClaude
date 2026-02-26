"use client";

import {
  ThreadPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  useThread,
} from "@assistant-ui/react";
import { MarkdownContent } from "@/components/parts/MarkdownContent";
import { ThinkingBlock } from "@/components/parts/ThinkingBlock";
import { ToolCallBlock } from "@/components/parts/ToolCallBlock";
import { FileLink } from "@/components/parts/FileLink";
import {
  RenderWidgetUI,
  AskUserQuestionUI,
} from "@/app/components/widgets";
import { StatusIndicator } from "@/components/parts/StatusIndicator";
import { useSessionAgent } from "@/hooks/useSessionAgent";
import { useAgentColors } from "@/hooks/useAgentColors";

function ThreadStatus() {
  const thread = useThread();
  const status = thread.isRunning ? "streaming" : "idle";
  return <StatusIndicator status={status} />;
}

export function ThreadView() {
  return (
    <ThreadPrimitive.Root className="flex h-full flex-col">
      <div className="flex items-center justify-end border-b px-4 py-1.5">
        <ThreadStatus />
      </div>

      <ThreadPrimitive.Viewport className="flex flex-1 flex-col overflow-y-auto px-4 pt-8">
        <ThreadPrimitive.Empty>
          <div className="flex flex-1 items-center justify-center">
            <p className="text-muted-foreground text-sm">
              Send a message to start
            </p>
          </div>
        </ThreadPrimitive.Empty>

        <ThreadPrimitive.Messages
          components={{
            UserMessage,
            AssistantMessage,
          }}
        />
      </ThreadPrimitive.Viewport>

      <div className="border-t bg-background p-4">
        <ComposerPrimitive.Root className="flex items-end gap-2">
          <ComposerPrimitive.Input
            placeholder="Type a message..."
            autoFocus
            className="flex-1 resize-none rounded-lg border bg-background px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <ComposerPrimitive.Send className="inline-flex h-10 items-center justify-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
            Send
          </ComposerPrimitive.Send>
        </ComposerPrimitive.Root>
      </div>
    </ThreadPrimitive.Root>
  );
}

function UserMessage() {
  const agent = useSessionAgent();
  const colors = useAgentColors(agent);

  return (
    <MessagePrimitive.Root className="mb-4 flex justify-end">
      <div
        className="max-w-[80%] rounded-lg px-4 py-2"
        style={{
          backgroundColor: colors.userBubbleBg,
          color: colors.userBubbleText,
        }}
      >
        <MessagePrimitive.Content />
      </div>
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  const agent = useSessionAgent();
  const colors = useAgentColors(agent);

  return (
    <MessagePrimitive.Root className="mb-4 flex justify-start">
      <div
        className="max-w-[80%] rounded-lg px-4 py-2"
        style={{
          backgroundColor: colors.assistantBubbleBg,
          color: colors.assistantBubbleText,
        }}
      >
        <MessagePrimitive.Content
          components={{
            Text: MarkdownContent,
            Reasoning: ThinkingBlock,
            File: FileLink,
            tools: {
              by_name: {
                telec sessions widget: RenderWidgetUI,
                AskUserQuestion: AskUserQuestionUI,
              },
              Fallback: ToolCallBlock,
            },
          }}
        />
      </div>
    </MessagePrimitive.Root>
  );
}

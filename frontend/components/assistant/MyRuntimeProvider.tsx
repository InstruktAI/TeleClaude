"use client";

import { type ReactNode, useMemo, useCallback, useState, useEffect } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import {
  useChatRuntime,
  AssistantChatTransport,
} from "@assistant-ui/react-ai-sdk";

interface Props {
  sessionId: string;
  children: ReactNode;
}

export function MyRuntimeProvider({ sessionId, children }: Props) {
  const [error, setError] = useState<string | null>(null);

  const handleError = useCallback((err: Error) => {
    console.error("Chat stream error:", err);
    setError(err.message || "An error occurred with the chat stream");
  }, []);

  // Clear error when session changes
  useEffect(() => {
    setError(null);
  }, [sessionId]);

  const transport = useMemo(
    () =>
      new AssistantChatTransport({
        api: "/api/chat",
        body: { sessionId },
      }),
    [sessionId],
  );

  const runtime = useChatRuntime({
    transport,
    onError: handleError,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {error && (
        <div
          className="bg-destructive/10 text-destructive px-4 py-2 mb-4 rounded-md border border-destructive/20 flex justify-between items-start gap-2"
          role="alert"
        >
          <div className="flex-1">
            <p className="text-sm font-medium">Stream Error</p>
            <p className="text-xs mt-1">{error}</p>
          </div>
          <button
            onClick={() => setError(null)}
            className="text-destructive hover:text-destructive/80 shrink-0 text-sm font-medium"
            aria-label="Dismiss error"
          >
            ✕
          </button>
        </div>
      )}
      {children}
    </AssistantRuntimeProvider>
  );
}

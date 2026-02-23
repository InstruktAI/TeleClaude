"use client";

import {
  type ReactNode,
  useMemo,
  useCallback,
  useState,
  useEffect,
  useRef,
} from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import {
  useAISDKRuntime,
  AssistantChatTransport,
} from "@assistant-ui/react-ai-sdk";
import { useChat } from "@ai-sdk/react";
import { useQuery } from "@tanstack/react-query";
import type { UIMessage } from "ai";
import type { MessageInfo } from "@/lib/api/types";
import { fetchSessions } from "@/lib/api/sessions";
import { SessionAgentProvider } from "@/hooks/useSessionAgent";
import { safeAgent, type AgentType } from "@/lib/theme/tokens";

interface Props {
  sessionId: string;
  children: ReactNode;
}

/**
 * Detect system-injected "user" messages that shouldn't appear as human input.
 * These are task notifications, hook feedback, context continuations, etc.
 */
function isSystemInjected(text: string): boolean {
  const t = text.trimStart();
  return (
    t.startsWith("<task-notification>") ||
    t.startsWith("Stop hook feedback:") ||
    t.startsWith("This session is being continued from a previous conversation") ||
    t === "[Request interrupted by user]" ||
    t.startsWith("<system-reminder>")
  );
}

/**
 * Convert daemon MessageInfo[] to AI SDK UIMessage[] format.
 * Groups consecutive same-role text messages into a single message.
 * Filters system-injected noise and reclassifies automated messages.
 */
function toUIMessages(messages: MessageInfo[]): UIMessage[] {
  const result: UIMessage[] = [];
  let current: UIMessage | null = null;

  for (const msg of messages) {
    if (msg.type !== "text") continue;

    // System-injected "user" messages get reclassified as assistant
    let role: "user" | "assistant";
    if (msg.role === "user" && isSystemInjected(msg.text)) {
      role = "assistant";
    } else {
      role = msg.role === "user" ? "user" : "assistant";
    }

    if (current && current.role === role) {
      const lastPart = current.parts[current.parts.length - 1];
      if (lastPart && lastPart.type === "text") {
        lastPart.text += "\n\n" + msg.text;
      }
    } else {
      current = {
        id: `hist-${msg.file_index}-${msg.entry_index}`,
        role,
        parts: [{ type: "text" as const, text: msg.text }],
      };
      result.push(current);
    }
  }

  return result;
}

export function MyRuntimeProvider({ sessionId, children }: Props) {
  const [error, setError] = useState<string | null>(null);

  // Fetch session info to get active agent type
  const { data: sessions } = useQuery({
    queryKey: ["sessions"],
    queryFn: fetchSessions,
  });
  const session = sessions?.find((s) => s.session_id === sessionId);
  const agent: AgentType = safeAgent(session?.active_agent ?? 'codex');

  const handleError = useCallback((err: Error) => {
    console.error("Chat stream error:", err);
    setError(err.message || "An error occurred with the chat stream");
  }, []);

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

  const chat = useChat({
    id: sessionId,
    transport,
    onError: handleError,
  });

  // Load session history into useChat on mount / session change
  const loadedRef = useRef<string | null>(null);
  useEffect(() => {
    if (loadedRef.current === sessionId) return;
    loadedRef.current = sessionId;

    fetch(`/api/sessions/${encodeURIComponent(sessionId)}/messages`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: { messages?: MessageInfo[] }) => {
        if (data.messages && data.messages.length > 0) {
          const uiMessages = toUIMessages(data.messages);
          chat.setMessages(uiMessages);
        }
      })
      .catch((err) => {
        console.warn("Failed to load session history:", err);
      });
  }, [sessionId, chat]);

  const runtime = useAISDKRuntime(chat);

  // Wire transport to runtime for streaming
  useEffect(() => {
    if (transport instanceof AssistantChatTransport) {
      transport.setRuntime(runtime);
    }
  }, [transport, runtime]);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <SessionAgentProvider value={{ agent }}>
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
      </SessionAgentProvider>
    </AssistantRuntimeProvider>
  );
}

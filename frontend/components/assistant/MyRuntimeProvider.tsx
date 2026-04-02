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
import type { AgentActivityEvent, MessageInfo } from "@/lib/api/types";
import { fetchSessions } from "@/lib/api/sessions";
import { SessionAgentProvider } from "@/hooks/useSessionAgent";
import { safeAgent, type AgentType } from "@/lib/theme/tokens";
import { useWS } from "@/lib/ws/WebSocketProvider";

interface Props {
  sessionId: string;
  children: ReactNode;
}

const HISTORY_REFRESH_DEBOUNCE_MS = 250;

/**
 * Convert daemon MessageInfo[] to AI SDK UIMessage[] format.
 * Groups consecutive same-role text messages into a single message.
 * Preserves canonical message text/reasoning from the daemon stream.
 */
function toUIMessages(messages: MessageInfo[]): UIMessage[] {
  const result: UIMessage[] = [];
  let current: UIMessage | null = null;

  for (const msg of messages) {
    if (msg.type !== "text" && msg.type !== "thinking") continue;

    const role = msg.role === "user" ? "user" : "assistant";

    if (msg.type === "thinking") {
      if (role !== "assistant") continue;
      if (!msg.text?.trim()) continue;

      const reasoningPart = {
        type: "reasoning" as const,
        text: msg.text,
      };

      if (current && current.role === role) {
        current.parts.push(reasoningPart as unknown as UIMessage["parts"][number]);
      } else {
        current = {
          id: `hist-think-${msg.file_index}-${msg.entry_index}`,
          role,
          parts: [reasoningPart as unknown as UIMessage["parts"][number]],
        };
        result.push(current);
      }
      continue;
    }
    if (!msg.text?.trim()) continue;

    if (current && current.role === role) {
      const lastPart = current.parts[current.parts.length - 1];
      if (lastPart && lastPart.type === "text") {
        lastPart.text += "\n\n" + msg.text;
      } else {
        current.parts.push({ type: "text" as const, text: msg.text });
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
  const { onEvent } = useWS();

  // Fetch session info to get active agent type
  const { data: sessions } = useQuery({
    queryKey: ["sessions"],
    queryFn: fetchSessions,
  });
  const session = sessions?.find((s) => s.session_id === sessionId);
  const agent: AgentType = safeAgent(session?.active_agent ?? "codex");

  const handleError = useCallback((err: Error) => {
    console.error("Chat stream error:", err);
    setError(err.message || "An error occurred with the chat stream");
  }, []);

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

  const setMessagesRef = useRef(chat.setMessages);
  const chatStatusRef = useRef(chat.status);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const historyAbortRef = useRef<AbortController | null>(null);
  const historyRequestIdRef = useRef(0);

  useEffect(() => {
    setMessagesRef.current = chat.setMessages;
    chatStatusRef.current = chat.status;
  }, [chat.setMessages, chat.status]);

  const loadSessionHistory = useCallback(async () => {
    historyAbortRef.current?.abort();
    const requestId = historyRequestIdRef.current + 1;
    historyRequestIdRef.current = requestId;
    const controller = new AbortController();
    historyAbortRef.current = controller;

    try {
      const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/messages`, {
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data = (await response.json()) as { messages?: MessageInfo[] };
      if (historyRequestIdRef.current !== requestId) return;

      const uiMessages =
        data.messages && data.messages.length > 0 ? toUIMessages(data.messages) : [];
      setMessagesRef.current(uiMessages);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      console.warn("Failed to load session history:", err);
    }
  }, [sessionId]);

  const scheduleHistoryRefresh = useCallback(() => {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
    }
    refreshTimerRef.current = setTimeout(() => {
      refreshTimerRef.current = null;
      void loadSessionHistory();
    }, HISTORY_REFRESH_DEBOUNCE_MS);
  }, [loadSessionHistory]);

  useEffect(() => {
    void loadSessionHistory();

    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
      historyAbortRef.current?.abort();
      historyAbortRef.current = null;
    };
  }, [loadSessionHistory]);

  useEffect(() => {
    const shouldRefreshForActivity = (event: AgentActivityEvent): boolean => {
      if (event.session_id !== sessionId) return false;
      if (chatStatusRef.current === "submitted" || chatStatusRef.current === "streaming") {
        return false;
      }

      // useChat already owns the local optimistic user-turn/send flow.
      // Only pull transcript history for remote/background activity.
      return true;
    };

    return onEvent("agent_activity", (event) => {
      if (event.event !== "agent_activity") return;
      const activityEvent = event as AgentActivityEvent;
      if (!shouldRefreshForActivity(activityEvent)) return;
      scheduleHistoryRefresh();
    });
  }, [onEvent, scheduleHistoryRefresh, sessionId]);

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

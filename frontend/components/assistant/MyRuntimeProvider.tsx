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
import { cleanMessageText, isSystemInjected, getCommandHeader } from "@/lib/utils/text";

interface Props {
  sessionId: string;
  children: ReactNode;
}

/**
 * Convert daemon MessageInfo[] to AI SDK UIMessage[] format.
 * Groups consecutive same-role text messages into a single message.
 * Filters system-injected noise and reclassifies automated messages.
 */
function toUIMessages(messages: MessageInfo[]): UIMessage[] {
  const result: UIMessage[] = [];
  let current: UIMessage | null = null;
  
  // Track if the current "burst" of same-role messages should be suppressed
  let burstSuppressionRole: string | null = null;

  for (const msg of messages) {
    if (msg.type !== "text") continue;

    const role = msg.role === "user" ? "user" : "assistant";

    // Reset burst suppression if the role switches
    if (current && current.role !== role) {
      burstSuppressionRole = null;
    }

    // Skip if we are currently suppressing this role's burst
    if (burstSuppressionRole === role) continue;

    const cleanedText = cleanMessageText(msg.text);
    const commandHeader = getCommandHeader(msg.text);

    // Filter out system messages
    if (isSystemInjected(cleanedText)) continue;

    // If it's a command message, extraction is handled by cleanMessageText.
    // We then trigger burst suppression to hide the "body" messages that follow.
    if (commandHeader) {
      burstSuppressionRole = role;
    }

    if (current && current.role === role) {
      // If it's a command, we FORCE a new message instead of merging
      // to keep it isolated from any previous text.
      if (commandHeader) {
        current = {
          id: `cmd-${msg.file_index}-${msg.entry_index}`,
          role,
          parts: [{ type: "text" as const, text: cleanedText }],
        };
        result.push(current);
      } else {
        const lastPart = current.parts[current.parts.length - 1];
        if (lastPart && lastPart.type === "text") {
          lastPart.text += "\n\n" + cleanedText;
        }
      }
    } else {
      current = {
        id: `hist-${msg.file_index}-${msg.entry_index}`,
        role,
        parts: [{ type: "text" as const, text: cleanedText }],
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
  const agent: AgentType = safeAgent(session?.active_agent ?? "codex");

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

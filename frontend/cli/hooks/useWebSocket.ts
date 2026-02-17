/**
 * WebSocket subscription hook for the TUI.
 *
 * Creates a `WebSocketManager` on mount, subscribes to all push event types,
 * and dispatches incoming events to the Zustand store. Exposes connection
 * state so the footer can display connectivity status.
 *
 * Auto-reconnect is handled internally by `WebSocketManager`.
 */

import { useEffect, useRef, useState, useCallback } from "react";

import { WebSocketManager } from "@/lib/api/websocket.js";
import type {
  AgentActivityEvent,
  SessionsInitialEvent,
  WsEvent,
} from "@/lib/api/types.js";
import { TelecAPIClient } from "@/lib/api/client.js";
import { tuiStore } from "@/lib/store/index.js";

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseWebSocketResult {
  connected: boolean;
  error: string | null;
}

export function useWebSocket(): UseWebSocketResult {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocketManager | null>(null);
  const apiRef = useRef<TelecAPIClient | null>(null);

  // Stable reference to the API client (created once).
  const getApi = useCallback(() => {
    if (!apiRef.current) {
      apiRef.current = new TelecAPIClient();
    }
    return apiRef.current;
  }, []);

  useEffect(() => {
    const ws = new WebSocketManager();
    wsRef.current = ws;

    // -- Lifecycle handlers --------------------------------------------------

    const unsubConnect = ws.onConnect(() => {
      setConnected(true);
      setError(null);
    });

    const unsubDisconnect = ws.onDisconnect(() => {
      setConnected(false);
    });

    const unsubError = ws.onError((err: Error) => {
      setError(err.message);
    });

    // -- Event dispatch to store ---------------------------------------------

    const unsubEvents = ws.onEvent("*", (event: WsEvent) => {
      const dispatch = tuiStore.getState().dispatch;

      switch (event.event) {
        case "sessions_initial": {
          const data = (event as SessionsInitialEvent).data;
          const ids = data.sessions.map((s) => s.session_id);
          dispatch({ type: "SYNC_SESSIONS", sessionIds: ids });
          break;
        }

        case "session_started":
        case "session_updated":
        case "session_closed": {
          // Re-fetch the full session list to stay in sync.
          // The store reconciles selection/scroll from the new ID set.
          getApi()
            .getSessions()
            .then((sessions) => {
              const ids = sessions.map((s) => s.session_id);
              tuiStore.getState().dispatch({
                type: "SYNC_SESSIONS",
                sessionIds: ids,
              });
            })
            .catch(() => {
              // Swallow fetch errors; the next WS event will retry.
            });
          break;
        }

        case "agent_activity": {
          const ae = event as AgentActivityEvent;
          dispatch({
            type: "AGENT_ACTIVITY",
            sessionId: ae.session_id,
            eventType: ae.type as
              | "user_prompt_submit"
              | "tool_use"
              | "tool_done"
              | "agent_stop",
            toolName: ae.tool_name,
            toolPreview: ae.tool_preview,
            summary: ae.summary,
            timestamp: ae.timestamp ?? undefined,
          });
          break;
        }

        case "todos_updated":
        case "todo_created":
        case "todo_updated":
        case "todo_removed": {
          getApi()
            .getTodos()
            .then((todos) => {
              const ids = todos.map((t) => t.slug);
              tuiStore.getState().dispatch({
                type: "SYNC_TODOS",
                todoIds: ids,
              });
            })
            .catch(() => {
              // Swallow; next event retries.
            });
          break;
        }

        // Other event types (projects_initial, computer_updated, etc.) can
        // be dispatched as the corresponding store intents are added.
        default:
          break;
      }
    });

    // -- Start connection ----------------------------------------------------

    ws.connect();

    // -- Cleanup on unmount --------------------------------------------------

    return () => {
      unsubConnect();
      unsubDisconnect();
      unsubError();
      unsubEvents();
      ws.close();
      wsRef.current = null;
    };
  }, [getApi]);

  return { connected, error };
}

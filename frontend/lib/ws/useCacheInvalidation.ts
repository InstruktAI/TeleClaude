"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useWS } from "./WebSocketProvider";
import type { WsEvent } from "./types";

/**
 * Listens to WebSocket events and invalidates relevant React Query caches.
 * Should be mounted once inside the chat layout (after both QueryProvider
 * and WebSocketProvider).
 */
export function useCacheInvalidation(): void {
  const { onEvent } = useWS();
  const queryClient = useQueryClient();

  useEffect(() => {
    const unsub = onEvent("*", (event: WsEvent) => {
      switch (event.event) {
        case "sessions_initial":
        case "session_started":
        case "session_updated":
        case "session_closed":
          queryClient.invalidateQueries({ queryKey: ["sessions"] });
          break;

        case "projects_initial":
        case "project_updated":
        case "projects_updated":
          queryClient.invalidateQueries({ queryKey: ["projects"] });
          break;

        case "computer_updated":
          queryClient.invalidateQueries({ queryKey: ["computers"] });
          break;

        case "todos_updated":
        case "todo_created":
        case "todo_updated":
        case "todo_removed":
          queryClient.invalidateQueries({ queryKey: ["todos"] });
          break;
      }
    });

    return unsub;
  }, [onEvent, queryClient]);
}

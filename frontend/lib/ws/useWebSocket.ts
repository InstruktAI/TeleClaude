"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { WsEvent, WsEventType, ConnectionStatus } from "./types";

const INITIAL_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 30_000;
const BACKOFF_MULTIPLIER = 2;

type EventHandler = (event: WsEvent) => void;

function getWsUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/ws`;
}

export interface UseWebSocketReturn {
  status: ConnectionStatus;
  subscribe: (computer: string, types: string[]) => void;
  unsubscribe: (computer: string) => void;
  refresh: () => void;
  onEvent: (type: WsEventType | "*", handler: EventHandler) => () => void;
}

export function useWebSocket(): UseWebSocketReturn {
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(INITIAL_BACKOFF_MS);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const runningRef = useRef(false);
  const handlersRef = useRef(new Map<WsEventType | "*", Set<EventHandler>>());
  const subscriptionsRef = useRef(new Map<string, string[]>());

  const send = useCallback((data: unknown) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(data));
    }
  }, []);

  const subscribe = useCallback(
    (computer: string, types: string[]) => {
      subscriptionsRef.current.set(computer, types);
      send({ subscribe: { computer, types } });
    },
    [send],
  );

  const unsubscribe = useCallback(
    (computer: string) => {
      subscriptionsRef.current.delete(computer);
      send({ unsubscribe: { computer } });
    },
    [send],
  );

  const refresh = useCallback(() => {
    send({ refresh: true });
  }, [send]);

  const onEvent = useCallback(
    (type: WsEventType | "*", handler: EventHandler): (() => void) => {
      const set = handlersRef.current.get(type) ?? new Set();
      set.add(handler);
      handlersRef.current.set(type, set);
      return () => {
        set.delete(handler);
        if (set.size === 0) handlersRef.current.delete(type);
      };
    },
    [],
  );

  useEffect(() => {
    runningRef.current = true;
    backoffRef.current = INITIAL_BACKOFF_MS;

    function connect() {
      if (!runningRef.current) return;

      setStatus((prev) =>
        prev === "disconnected" ? "connecting" : "reconnecting",
      );

      const ws = new WebSocket(getWsUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        backoffRef.current = INITIAL_BACKOFF_MS;
        setStatus("connected");

        // Replay subscriptions
        for (const [computer, types] of subscriptionsRef.current) {
          ws.send(JSON.stringify({ subscribe: { computer, types } }));
        }
      };

      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data as string);
          if (!data.event) return;

          // Handle bridge status events
          if (data.event === "_bridge_connected") {
            setStatus("connected");
            return;
          }
          if (data.event === "_bridge_disconnected") {
            if (data.data?.reconnecting) {
              setStatus("reconnecting");
            }
            return;
          }

          // Dispatch to typed handlers
          const typedHandlers = handlersRef.current.get(data.event);
          if (typedHandlers) {
            for (const handler of typedHandlers) {
              try {
                handler(data as WsEvent);
              } catch {
                // swallow handler errors
              }
            }
          }

          // Dispatch to wildcard handlers
          const wildcardHandlers = handlersRef.current.get("*");
          if (wildcardHandlers) {
            for (const handler of wildcardHandlers) {
              try {
                handler(data as WsEvent);
              } catch {
                // swallow
              }
            }
          }
        } catch {
          // ignore non-JSON messages
        }
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (!runningRef.current) {
          setStatus("disconnected");
          return;
        }
        setStatus("reconnecting");
        scheduleReconnect();
      };

      ws.onerror = () => {
        // Close event follows
      };
    }

    function scheduleReconnect() {
      if (!runningRef.current) return;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);

      const jitter = 1 + (Math.random() * 2 - 1) * 0.3;
      const delay = Math.min(backoffRef.current * jitter, MAX_BACKOFF_MS);

      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null;
        backoffRef.current = Math.min(
          backoffRef.current * BACKOFF_MULTIPLIER,
          MAX_BACKOFF_MS,
        );
        connect();
      }, delay);
    }

    connect();

    return () => {
      runningRef.current = false;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      setStatus("disconnected");
    };
  }, []);

  return { status, subscribe, unsubscribe, refresh, onEvent };
}

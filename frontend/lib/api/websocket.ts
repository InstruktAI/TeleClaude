/**
 * WebSocket manager for TeleClaude daemon push events.
 *
 * Connects to the daemon WebSocket via Unix socket using the `ws` library.
 * Provides auto-reconnect with exponential backoff, per-computer
 * subscribe/unsubscribe, and typed event dispatch.
 */

import http from "node:http";
import WebSocket from "ws";

import type {
  WsClientMessage,
  WsEvent,
  WsEventType,
} from "./types.js";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const DEFAULT_SOCKET_PATH = "/tmp/teleclaude-api.sock";
const WS_PATH = "/ws";

const INITIAL_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 30_000;
const BACKOFF_MULTIPLIER = 2;
const JITTER_FACTOR = 0.3; // +/- 30% random jitter

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type EventHandler<T extends WsEvent = WsEvent> = (event: T) => void;
type LifecycleHandler = () => void;
type ErrorHandler = (error: Error) => void;

export interface WebSocketManagerOptions {
  socketPath?: string;
  /** Subscription types to send on initial connect (default: ["sessions", "preparation"]) */
  initialSubscriptions?: string[];
}

// ---------------------------------------------------------------------------
// Event type guard
// ---------------------------------------------------------------------------

const KNOWN_EVENT_TYPES = new Set<string>([
  "sessions_initial",
  "projects_initial",
  "preparation_initial",
  "session_started",
  "session_updated",
  "session_closed",
  "computer_updated",
  "project_updated",
  "projects_updated",
  "todos_updated",
  "todo_created",
  "todo_updated",
  "todo_removed",
  "error",
  "agent_activity",
]);

function isWsEvent(data: unknown): data is WsEvent {
  if (typeof data !== "object" || data === null) return false;
  const obj = data as Record<string, unknown>;
  return typeof obj.event === "string" && KNOWN_EVENT_TYPES.has(obj.event);
}

// ---------------------------------------------------------------------------
// Manager
// ---------------------------------------------------------------------------

export class WebSocketManager {
  private readonly socketPath: string;
  private readonly initialSubscriptions: string[];

  private ws: WebSocket | null = null;
  private running = false;
  private backoff = INITIAL_BACKOFF_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  // Event handlers: per-event-type + wildcard
  private handlers = new Map<WsEventType | "*", Set<EventHandler>>();
  private connectHandlers = new Set<LifecycleHandler>();
  private disconnectHandlers = new Set<LifecycleHandler>();
  private errorHandlers = new Set<ErrorHandler>();

  constructor(opts?: WebSocketManagerOptions) {
    this.socketPath =
      opts?.socketPath ??
      process.env.DAEMON_SOCKET_PATH ??
      DEFAULT_SOCKET_PATH;
    this.initialSubscriptions = opts?.initialSubscriptions ?? [
      "sessions",
      "preparation",
    ];
  }

  // ---- lifecycle --------------------------------------------------------

  /** Start the WebSocket connection loop. Idempotent. */
  connect(): void {
    if (this.running) return;
    this.running = true;
    this.backoff = INITIAL_BACKOFF_MS;
    this.attemptConnect();
  }

  /** Disconnect and stop reconnection. */
  close(): void {
    this.running = false;
    this.clearReconnectTimer();
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // ignore close errors
      }
      this.ws = null;
    }
  }

  /** Whether the WebSocket is currently open. */
  get connected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  // ---- subscription management ------------------------------------------

  /** Subscribe to updates for a specific computer. */
  subscribe(computer: string, types: string[]): void {
    this.send({ subscribe: { computer, types } });
  }

  /** Unsubscribe from a computer's updates. */
  unsubscribe(computer: string): void {
    this.send({ unsubscribe: { computer } });
  }

  /** Request a full refresh from the server. */
  refresh(): void {
    this.send({ refresh: true });
  }

  // ---- event registration -----------------------------------------------

  /** Register a handler for a specific event type. Returns an unsubscribe function. */
  onEvent<T extends WsEvent = WsEvent>(
    type: WsEventType | "*",
    handler: EventHandler<T>,
  ): () => void {
    const set = this.handlers.get(type) ?? new Set();
    set.add(handler as EventHandler);
    this.handlers.set(type, set);
    return () => {
      set.delete(handler as EventHandler);
      if (set.size === 0) this.handlers.delete(type);
    };
  }

  /** Register a handler called when the WebSocket connects. Returns an unsubscribe function. */
  onConnect(handler: LifecycleHandler): () => void {
    this.connectHandlers.add(handler);
    return () => {
      this.connectHandlers.delete(handler);
    };
  }

  /** Register a handler called when the WebSocket disconnects. Returns an unsubscribe function. */
  onDisconnect(handler: LifecycleHandler): () => void {
    this.disconnectHandlers.add(handler);
    return () => {
      this.disconnectHandlers.delete(handler);
    };
  }

  /** Register an error handler. Returns an unsubscribe function. */
  onError(handler: ErrorHandler): () => void {
    this.errorHandlers.add(handler);
    return () => {
      this.errorHandlers.delete(handler);
    };
  }

  // ---- internals --------------------------------------------------------

  private attemptConnect(): void {
    if (!this.running) return;

    // Clean up any previous connection
    if (this.ws) {
      this.ws.removeAllListeners();
      this.ws = null;
    }

    // Connect via Unix socket using http.Agent with socketPath
    const agent = new http.Agent({
      // @ts-expect-error -- Node.js http.Agent supports socketPath internally
      socketPath: this.socketPath,
    });

    const wsInstance = new WebSocket(`ws://localhost${WS_PATH}`, {
      agent,
    });

    wsInstance.on("open", () => {
      this.ws = wsInstance;
      this.backoff = INITIAL_BACKOFF_MS;

      // Send initial subscriptions
      if (this.initialSubscriptions.length > 0) {
        this.send({
          subscribe: {
            computer: "local",
            types: this.initialSubscriptions,
          },
        });
      }

      for (const handler of this.connectHandlers) {
        try {
          handler();
        } catch {
          // swallow handler errors
        }
      }
    });

    wsInstance.on("message", (data: WebSocket.Data) => {
      this.handleMessage(data);
    });

    wsInstance.on("close", () => {
      this.ws = null;
      for (const handler of this.disconnectHandlers) {
        try {
          handler();
        } catch {
          // swallow
        }
      }
      this.scheduleReconnect();
    });

    wsInstance.on("error", (err: Error) => {
      for (const handler of this.errorHandlers) {
        try {
          handler(err);
        } catch {
          // swallow
        }
      }
      // Close event will follow, which triggers reconnect
    });
  }

  private handleMessage(data: WebSocket.Data): void {
    let parsed: unknown;
    try {
      const text = typeof data === "string" ? data : data.toString("utf-8");
      parsed = JSON.parse(text);
    } catch {
      return; // invalid JSON, discard
    }

    if (!isWsEvent(parsed)) return;

    const event = parsed;

    // Dispatch to type-specific handlers
    const typeHandlers = this.handlers.get(event.event);
    if (typeHandlers) {
      for (const handler of typeHandlers) {
        try {
          handler(event);
        } catch {
          // swallow handler errors to protect the message loop
        }
      }
    }

    // Dispatch to wildcard handlers
    const wildcardHandlers = this.handlers.get("*");
    if (wildcardHandlers) {
      for (const handler of wildcardHandlers) {
        try {
          handler(event);
        } catch {
          // swallow
        }
      }
    }
  }

  private send(message: WsClientMessage): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    try {
      this.ws.send(JSON.stringify(message));
    } catch {
      // send failure; close event will handle reconnect
    }
  }

  private scheduleReconnect(): void {
    if (!this.running) return;
    this.clearReconnectTimer();

    // Apply jitter: delay * (1 +/- jitter)
    const jitter = 1 + (Math.random() * 2 - 1) * JITTER_FACTOR;
    const delay = Math.min(this.backoff * jitter, MAX_BACKOFF_MS);

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.backoff = Math.min(this.backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_MS);
      this.attemptConnect();
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}

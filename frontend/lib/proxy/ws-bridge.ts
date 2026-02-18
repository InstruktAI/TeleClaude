/**
 * WebSocket bridge between browser clients and daemon WS.
 *
 * Each browser WebSocket connection gets a corresponding daemon WS
 * connection. Messages are forwarded bidirectionally. The bridge handles:
 * - Auth validation (session cookie check on upgrade)
 * - Identity injection into subscription messages
 * - Daemon disconnect detection with reconnection + subscription replay
 * - Clean teardown when either side disconnects
 */

import http from "node:http";
import WebSocket from "ws";

const DAEMON_SOCKET_PATH =
  process.env.DAEMON_SOCKET_PATH ?? "/tmp/teleclaude-api.sock";
const DAEMON_WS_PATH = "/ws";

const INITIAL_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 30_000;
const BACKOFF_MULTIPLIER = 2;
const JITTER_FACTOR = 0.3;

interface BridgeClient {
  browser: WebSocket;
  daemon: WebSocket | null;
  subscriptions: Map<string, string[]>;
  identity: { email: string; name?: string; role?: string };
  backoff: number;
  reconnectTimer: ReturnType<typeof setTimeout> | null;
  running: boolean;
}

function createDaemonConnection(): WebSocket {
  const agent = new http.Agent({
    // @ts-expect-error -- Node.js http.Agent supports socketPath
    socketPath: DAEMON_SOCKET_PATH,
  });

  return new WebSocket(`ws://localhost${DAEMON_WS_PATH}`, { agent });
}

function jitteredDelay(backoff: number): number {
  const jitter = 1 + (Math.random() * 2 - 1) * JITTER_FACTOR;
  return Math.min(backoff * jitter, MAX_BACKOFF_MS);
}

function replaySubscriptions(client: BridgeClient): void {
  if (!client.daemon || client.daemon.readyState !== WebSocket.OPEN) return;
  for (const [computer, types] of client.subscriptions) {
    client.daemon.send(JSON.stringify({ subscribe: { computer, types } }));
  }
}

function connectToDaemon(client: BridgeClient): void {
  if (!client.running) return;

  const daemon = createDaemonConnection();

  daemon.on("open", () => {
    client.daemon = daemon;
    client.backoff = INITIAL_BACKOFF_MS;
    replaySubscriptions(client);

    // Notify browser of reconnection
    if (client.browser.readyState === WebSocket.OPEN) {
      client.browser.send(
        JSON.stringify({ event: "_bridge_connected", data: {} }),
      );
    }
  });

  daemon.on("message", (data) => {
    // Forward daemon -> browser
    if (client.browser.readyState === WebSocket.OPEN) {
      client.browser.send(
        typeof data === "string" ? data : data.toString("utf-8"),
      );
    }
  });

  daemon.on("close", () => {
    client.daemon = null;
    if (client.browser.readyState === WebSocket.OPEN) {
      client.browser.send(
        JSON.stringify({
          event: "_bridge_disconnected",
          data: { reconnecting: client.running },
        }),
      );
    }
    scheduleDaemonReconnect(client);
  });

  daemon.on("error", () => {
    // Close event follows; reconnect happens there
  });
}

function scheduleDaemonReconnect(client: BridgeClient): void {
  if (!client.running) return;
  if (client.reconnectTimer) clearTimeout(client.reconnectTimer);

  const delay = jitteredDelay(client.backoff);
  client.reconnectTimer = setTimeout(() => {
    client.reconnectTimer = null;
    client.backoff = Math.min(
      client.backoff * BACKOFF_MULTIPLIER,
      MAX_BACKOFF_MS,
    );
    connectToDaemon(client);
  }, delay);
}

function teardown(client: BridgeClient): void {
  client.running = false;
  if (client.reconnectTimer) {
    clearTimeout(client.reconnectTimer);
    client.reconnectTimer = null;
  }
  if (client.daemon) {
    try {
      client.daemon.close();
    } catch {
      // ignore
    }
    client.daemon = null;
  }
}

/**
 * Handle a new browser WebSocket connection by creating a bridge
 * to the daemon.
 */
export function bridgeConnection(
  browserWs: WebSocket,
  identity: { email: string; name?: string; role?: string },
): void {
  const client: BridgeClient = {
    browser: browserWs,
    daemon: null,
    subscriptions: new Map(),
    identity,
    backoff: INITIAL_BACKOFF_MS,
    reconnectTimer: null,
    running: true,
  };

  // Browser -> daemon message forwarding
  browserWs.on("message", (data) => {
    const text = typeof data === "string" ? data : data.toString("utf-8");

    // Track subscriptions for replay on reconnect
    try {
      const msg = JSON.parse(text);
      if (msg.subscribe?.computer && msg.subscribe?.types) {
        client.subscriptions.set(msg.subscribe.computer, msg.subscribe.types);
      } else if (msg.unsubscribe?.computer) {
        client.subscriptions.delete(msg.unsubscribe.computer);
      }
    } catch {
      // Not JSON; forward as-is
    }

    if (client.daemon && client.daemon.readyState === WebSocket.OPEN) {
      client.daemon.send(text);
    }
  });

  browserWs.on("close", () => {
    teardown(client);
  });

  browserWs.on("error", () => {
    teardown(client);
  });

  // Start daemon connection
  connectToDaemon(client);
}

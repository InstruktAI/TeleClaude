/**
 * Browser-side WebSocket types.
 *
 * Reuses event types from the shared API types and adds
 * browser-specific connection state.
 */

export type { WsEvent, WsEventType, WsClientMessage } from "@/lib/api/types";

export type ConnectionStatus =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected";

export interface BridgeConnectedEvent {
  event: "_bridge_connected";
  data: Record<string, never>;
}

export interface BridgeDisconnectedEvent {
  event: "_bridge_disconnected";
  data: { reconnecting: boolean };
}

export type BridgeEvent = BridgeConnectedEvent | BridgeDisconnectedEvent;

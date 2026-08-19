/**
 * Frontend API type surface.
 *
 * Python-derived contracts are generated in ./generated-types.ts.
 * Frontend-only unions and client message wrappers stay here.
 */

export * from './generated-types';

import type {
  AgentActivityEvent,
  AgentAvailabilityEvent,
  ErrorEvent,
  ProjectsInitialEvent,
  RefreshEvent,
  SessionClosedEvent,
  SessionStartedEvent,
  SessionStatusEvent,
  SessionUpdatedEvent,
  SessionsInitialEvent,
} from './generated-types';

export type PaneThemingMode = 'off' | 'highlight' | 'highlight2' | 'agent' | 'agent_plus' | 'full' | 'semi';

/** Agent runtime names the frontend models; the daemon now emits this as an inline union. */
export type AgentName = 'claude' | 'gemini' | 'codex';

/** Discriminated union of all WebSocket events. Discriminator: `event` field. */
export type WsEvent =
  | SessionsInitialEvent
  | ProjectsInitialEvent
  | SessionStartedEvent
  | SessionUpdatedEvent
  | SessionClosedEvent
  | SessionStatusEvent
  | AgentAvailabilityEvent
  | RefreshEvent
  | ErrorEvent
  | AgentActivityEvent;

/** All possible values for the `event` discriminator field. */
export type WsEventType = WsEvent['event'];

export interface SubscribeMessage {
  subscribe: {
    computer: string;
    types: string[];
  };
}

export interface UnsubscribeMessage {
  unsubscribe: {
    computer: string;
  };
}

export interface RefreshMessage {
  refresh: true;
}

export type WsClientMessage = SubscribeMessage | UnsubscribeMessage | RefreshMessage;

export interface StatusResponse {
  status: string;
  result?: unknown;
}

export interface HealthResponse {
  status: 'ok';
}

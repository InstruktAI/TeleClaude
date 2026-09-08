'use client';

/**
 * Context for sharing the active session's agent type with message components.
 *
 * This allows AssistantMessage to know which agent colors to use for theming.
 */

import { createContext, useContext } from 'react';
import type { AgentType } from '@/lib/theme/tokens';

interface SessionAgentContextValue {
  /** Canonical agent type for the active session, or `undefined` when not yet known. */
  agent: AgentType | undefined;
}

const SessionAgentContext = createContext<SessionAgentContextValue | undefined>(undefined);

export const SessionAgentProvider = SessionAgentContext.Provider;

/**
 * Hook to access the active session's agent type.
 *
 * Must be used within SessionAgentProvider. Returns `undefined` before
 * session info has loaded or when the session carries no known agent —
 * callers render neutral presentation rather than assuming an identity.
 */
export function useSessionAgent(): AgentType | undefined {
  const context = useContext(SessionAgentContext);
  return context?.agent;
}

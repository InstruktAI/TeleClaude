'use client'

/**
 * Context for sharing the active session's agent type with message components.
 *
 * This allows AssistantMessage to know which agent colors to use for theming.
 */

import { createContext, useContext } from 'react'
import type { AgentType } from '@/lib/theme/tokens'

interface SessionAgentContextValue {
  /** Agent type for the active session (claude, gemini, codex) */
  agent: AgentType
}

const SessionAgentContext = createContext<SessionAgentContextValue | undefined>(undefined)

export const SessionAgentProvider = SessionAgentContext.Provider

/**
 * Hook to access the active session's agent type.
 *
 * Must be used within SessionAgentProvider.
 */
export function useSessionAgent(): AgentType {
  const context = useContext(SessionAgentContext)
  if (!context) {
    // Default to 'codex' if context is not available
    // This gracefully handles cases where the session info hasn't loaded yet
    return 'codex'
  }
  return context.agent
}

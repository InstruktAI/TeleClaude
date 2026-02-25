'use client'

/**
 * AgentTheming context for peaceful vs themed mode.
 *
 * Peaceful mode: neutral colors for all bubbles and sidebar
 * Themed mode: agent-colored assistant bubbles, orange user bubbles, colored sidebar
 *
 * State persists strictly to browser localStorage.
 */

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

interface AgentThemingContextValue {
  /** True = themed mode (agent colors visible), False = peaceful mode (neutral) */
  isThemed: boolean
  /** Toggle theming mode and persist to localStorage */
  setThemed: (themed: boolean) => void
}

const AgentThemingContext = createContext<AgentThemingContextValue | undefined>(undefined)

const STORAGE_KEY = 'teleclaude_agent_theming'

interface AgentThemingProviderProps {
  children: ReactNode
}

/**
 * Provider for peaceful vs themed mode state.
 * Persists strictly to localStorage.
 */
export function AgentThemingProvider({ children }: AgentThemingProviderProps) {
  const [isThemed, setIsThemed] = useState(false)
  const [isInitialized, setIsInitialized] = useState(false)

  // Read initial state from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored !== null) {
      setIsThemed(stored === 'true')
    } else {
      // Default to themed mode if nothing is set
      setIsThemed(true)
    }
    setIsInitialized(true)
  }, [])

  // Update state and localStorage
  const setThemed = (themed: boolean) => {
    setIsThemed(themed)
    localStorage.setItem(STORAGE_KEY, String(themed))
  }

  // Avoid flash of neutral state during initialization
  if (!isInitialized) {
    return null
  }

  return (
    <AgentThemingContext.Provider value={{ isThemed, setThemed }}>
      {children}
    </AgentThemingContext.Provider>
  )
}

/**
 * Hook to access theming mode and toggle function.
 */
export function useAgentTheming(): AgentThemingContextValue {
  const context = useContext(AgentThemingContext)
  if (!context) {
    throw new Error('useAgentTheming must be used within AgentThemingProvider')
  }
  return context
}

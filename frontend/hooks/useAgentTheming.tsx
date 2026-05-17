'use client'

/**
 * AgentTheming context for peaceful vs themed mode.
 *
 * Peaceful mode: neutral colors for all bubbles and sidebar
 * Themed mode: agent-colored assistant bubbles, orange user bubbles, colored sidebar
 *
 * State persists strictly to browser localStorage.
 */

import { createContext, useContext, useSyncExternalStore, type ReactNode } from 'react'

interface AgentThemingContextValue {
  /** True = themed mode (agent colors visible), False = peaceful mode (neutral) */
  isThemed: boolean
  /** Toggle theming mode and persist to localStorage */
  setThemed: (themed: boolean) => void
}

const AgentThemingContext = createContext<AgentThemingContextValue | undefined>(undefined)

export const STORAGE_KEY = 'teleclaude_agent_theming'

const subscribers = new Set<() => void>()

function subscribe(callback: () => void) {
  subscribers.add(callback)

  const handleStorage = (e: StorageEvent) => {
    if (e.key === STORAGE_KEY) {
      callback()
    }
  }

  window.addEventListener('storage', handleStorage)
  return () => {
    window.removeEventListener('storage', handleStorage)
    subscribers.delete(callback)
  }
}

function getSnapshot(): boolean {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored !== null) {
      return stored === 'true'
    }
    return true // Default to themed mode
  } catch (e) {
    // Fall back to themed mode to keep the UI renderable when browser storage is unavailable
    return true
  }
}

function getServerSnapshot(): boolean {
  return true // Same default value for server/hydration consistency
}

interface AgentThemingProviderProps {
  children: ReactNode
}

/**
 * Provider for peaceful vs themed mode state.
 * Persists strictly to localStorage.
 */
export function AgentThemingProvider({ children }: AgentThemingProviderProps) {
  const isThemed = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)

  // Update state and localStorage
  const setThemed = (themed: boolean) => {
    try {
      localStorage.setItem(STORAGE_KEY, String(themed))
    } catch (e) {
      // Ignore storage errors, still notify local subscribers
    }
    // Synchronously notify local external-store subscribers
    subscribers.forEach((callback) => callback())
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

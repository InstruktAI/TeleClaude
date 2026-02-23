'use client'

/**
 * AgentTheming context for peaceful vs themed mode.
 *
 * Peaceful mode: neutral colors for all bubbles and sidebar
 * Themed mode: agent-colored assistant bubbles, orange user bubbles, colored sidebar
 *
 * State persists to daemon API via the `pane_theming_mode` setting:
 *   - off → peaceful (false)
 *   - agent_plus → themed (true)
 */

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

interface AgentThemingContextValue {
  /** True = themed mode (agent colors visible), False = peaceful mode (neutral) */
  isThemed: boolean
  /** Toggle theming mode and persist to daemon API */
  setThemed: (themed: boolean) => void
}

const AgentThemingContext = createContext<AgentThemingContextValue | undefined>(undefined)

interface AgentThemingProviderProps {
  children: ReactNode
}

/**
 * Provider for peaceful vs themed mode state.
 *
 * On mount: reads pane_theming_mode from daemon API
 * On change: persists to daemon API via PATCH /api/settings
 */
export function AgentThemingProvider({ children }: AgentThemingProviderProps) {
  const [isThemed, setIsThemed] = useState(false)
  const [isInitialized, setIsInitialized] = useState(false)

  // Read initial state from daemon API on mount
  useEffect(() => {
    async function loadThemingMode() {
      try {
        const res = await fetch('/api/settings')
        if (!res.ok) {
          console.warn('Failed to load theming mode from daemon API, using default (peaceful)')
          setIsInitialized(true)
          return
        }

        const data = await res.json()
        const mode = data.pane_theming_mode

        // Map daemon API values to boolean:
        //   "off" → false (peaceful)
        //   "agent_plus" (or any other value) → true (themed)
        setIsThemed(mode !== 'off')
        setIsInitialized(true)
      } catch (err) {
        console.error('Error loading theming mode:', err)
        setIsInitialized(true)
      }
    }

    loadThemingMode()
  }, [])

  // Persist theming mode changes to daemon API
  const setThemed = async (themed: boolean) => {
    setIsThemed(themed)

    // Map boolean to daemon API values
    const mode = themed ? 'agent_plus' : 'off'

    try {
      const res = await fetch('/api/settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pane_theming_mode: mode }),
      })

      if (!res.ok) {
        console.error('Failed to persist theming mode to daemon API')
      }
    } catch (err) {
      console.error('Error persisting theming mode:', err)
    }
  }

  // Don't render children until initial state is loaded
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
 *
 * Must be used inside AgentThemingProvider.
 */
export function useAgentTheming(): AgentThemingContextValue {
  const context = useContext(AgentThemingContext)
  if (!context) {
    throw new Error('useAgentTheming must be used within AgentThemingProvider')
  }
  return context
}

'use client'

/**
 * Toggle for peaceful vs themed mode.
 *
 * Peaceful: neutral gray colors for all bubbles and sidebar
 * Themed: agent-colored assistant bubbles, orange user bubbles, colored sidebar
 */

import { Palette } from 'lucide-react'
import { useAgentTheming } from '@/hooks/useAgentTheming'

export function ThemingToggle() {
  const { isThemed, setThemed } = useAgentTheming()

  return (
    <button
      onClick={() => setThemed(!isThemed)}
      className={`
        inline-flex h-8 w-8 items-center justify-center rounded-md
        transition-colors
        ${
          isThemed
            ? 'bg-primary/10 text-primary hover:bg-primary/20'
            : 'text-muted-foreground hover:bg-accent'
        }
      `}
      aria-label={isThemed ? 'Switch to peaceful mode' : 'Switch to themed mode'}
      title={isThemed ? 'Themed (agent colors visible)' : 'Peaceful (neutral)'}
    >
      <Palette className="h-4 w-4" />
    </button>
  )
}

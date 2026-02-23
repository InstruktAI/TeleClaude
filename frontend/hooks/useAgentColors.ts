'use client'

/**
 * Hook for resolving agent and user colors based on theming mode.
 *
 * Returns CSS variable references that switch between:
 *   - Themed mode: agent-specific colors and orange user bubbles
 *   - Peaceful mode: neutral grays for everything
 */

import { useAgentTheming } from './useAgentTheming'
import type { AgentType } from '@/lib/theme/tokens'

export interface AgentColors {
  /** Background color for assistant messages (CSS var reference) */
  assistantBubbleBg: string
  /** Text color for assistant messages (CSS var reference) */
  assistantBubbleText: string
  /** Background color for user messages (CSS var reference) */
  userBubbleBg: string
  /** Text color for user messages (CSS var reference) */
  userBubbleText: string
  /** Text color for sidebar session items (CSS var reference) */
  sidebarText: string
}

/**
 * Get color CSS variable references for a specific agent.
 *
 * The returned values are CSS var() references, not actual hex values.
 * This ensures colors respond to theme changes and theme.local.css overrides.
 *
 * @param agent - Agent type (claude, gemini, codex)
 * @returns Object with CSS var references for different UI elements
 */
export function useAgentColors(agent: AgentType): AgentColors {
  const { isThemed } = useAgentTheming()

  if (isThemed) {
    // Themed mode: agent-colored assistant bubbles, orange user bubbles, agent sidebar
    return {
      assistantBubbleBg: `var(--agent-${agent}-subtle)`,
      assistantBubbleText: `var(--text-primary)`,
      userBubbleBg: 'var(--user-bubble-bg)',
      userBubbleText: 'var(--user-bubble-text)',
      sidebarText: `var(--agent-${agent}-normal)`,
    }
  } else {
    // Peaceful mode: neutral grays for everything
    return {
      assistantBubbleBg: 'var(--peaceful-muted)',
      assistantBubbleText: 'var(--text-primary)',
      userBubbleBg: 'var(--peaceful-muted)',
      userBubbleText: 'var(--text-primary)',
      sidebarText: 'var(--text-secondary)',
    }
  }
}

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
      assistantBubbleBg: `var(--tc-agent-${agent}-subtle)`,
      assistantBubbleText: `var(--tc-text-primary)`,
      userBubbleBg: 'var(--tc-user-bubble-bg)',
      userBubbleText: 'var(--tc-user-bubble-text)',
      sidebarText: `var(--tc-agent-${agent}-normal)`,
    }
  } else {
    // Peaceful mode: distinct neutral backgrounds for assistant vs user
    return {
      assistantBubbleBg: 'var(--tc-bg-surface)',
      assistantBubbleText: 'var(--tc-text-primary)',
      userBubbleBg: 'var(--tc-peaceful-muted)',
      userBubbleText: 'var(--tc-text-primary)',
      sidebarText: 'var(--tc-text-secondary)',
    }
  }
}

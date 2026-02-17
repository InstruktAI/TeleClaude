/**
 * Agent type badge micro component.
 *
 * Renders a compact colored badge indicating the agent type:
 *   [C] for Claude, [G] for Gemini, [X] for Codex.
 *
 * Badge uses the agent's theme color as background with contrasting foreground.
 *
 * Source: teleclaude/cli/tui/views/sessions.py (_SessionBadgeComponent)
 */

import React from "react";
import { Text } from "ink";

import { agentBadge } from "@/lib/theme/ink-colors.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface BadgeProps {
  /** Agent type identifier (claude, gemini, codex) */
  agent: string;
  /** Whether the badge is in a focused/selected row */
  focused?: boolean;
}

// ---------------------------------------------------------------------------
// Agent letter mapping
// ---------------------------------------------------------------------------

const AGENT_LETTERS: Record<string, string> = {
  claude: "C",
  gemini: "G",
  codex: "X",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Badge({ agent, focused = false }: BadgeProps) {
  const letter = AGENT_LETTERS[agent] ?? "?";
  const fmt = agentBadge(agent, focused);

  return <Text>{fmt(`[${letter}]`)}</Text>;
}

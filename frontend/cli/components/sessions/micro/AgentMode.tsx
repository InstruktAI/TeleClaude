/**
 * Thinking mode indicator micro component.
 *
 * Renders a compact icon indicating the agent's thinking mode:
 *   fast, med, slow
 *
 * Source: teleclaude/cli/tui/views/sessions.py (_build_session_row_model)
 */

import React from "react";
import { Text } from "ink";

import { agentColor } from "@/lib/theme/ink-colors.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AgentModeProps {
  /** Thinking mode (fast, med, slow) */
  mode: string;
  /** Agent type for theming */
  agent: string;
}

// ---------------------------------------------------------------------------
// Mode display mapping
// ---------------------------------------------------------------------------

const MODE_LABELS: Record<string, string> = {
  fast: "fast",
  med: "med",
  slow: "slow",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AgentMode({ mode, agent }: AgentModeProps) {
  const label = MODE_LABELS[mode] ?? mode;
  const fmt = agentColor(agent, "muted");

  return <Text>{fmt(label)}</Text>;
}

/**
 * Session title text micro component.
 *
 * Renders the session title with selection-aware styling.
 * Title is truncated to maxLen when provided.
 *
 * Source: teleclaude/cli/tui/views/sessions.py (_build_session_row_model)
 */

import React from "react";
import { Text } from "ink";

import { agentColor } from "@/lib/theme/ink-colors.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TitleProps {
  /** Session title text */
  text: string;
  /** Agent type for theming */
  agent: string;
  /** Whether the row is selected */
  selected?: boolean;
  /** Whether the session is headless (dimmed) */
  headless?: boolean;
  /** Maximum display length for truncation */
  maxLen?: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Title({
  text,
  agent,
  selected = false,
  headless = false,
  maxLen,
}: TitleProps) {
  let display = text;
  if (maxLen && display.length > maxLen) {
    display = display.slice(0, maxLen - 1) + "\u2026";
  }

  const level = headless ? "subtle" : "normal";
  const fmt = agentColor(agent, selected ? "highlight" : level);

  return <Text bold={selected}>{fmt(`"${display}"`)}</Text>;
}

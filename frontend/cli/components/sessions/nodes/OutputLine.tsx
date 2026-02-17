/**
 * Output summary/activity line for a session.
 *
 * Shows the last output summary from the agent, or a working placeholder
 * when the agent is actively processing. Supports temporary highlights
 * for tool use events.
 *
 * Source: teleclaude/cli/tui/views/sessions.py (_build_session_row_model, output line)
 */

import React from "react";
import { Box, Text } from "ink";

import { agentColor } from "@/lib/theme/ink-colors.js";
import { formatRelativeTime } from "@/lib/utils/time.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OutputLineProps {
  /** Agent type for theming */
  agent: string;
  /** Output summary text (empty if placeholder should show) */
  outputText: string;
  /** Output timestamp (ISO string) */
  outputAt: string | null | undefined;
  /** Activity timestamp for working placeholder */
  activityAt: string | null | undefined;
  /** Whether this output is actively highlighted */
  isHighlighted: boolean;
  /** Whether to show a temporary working placeholder */
  isWorking: boolean;
  /** Active tool preview text (when agent is using a tool) */
  toolPreview: string | null | undefined;
  /** Indent prefix string */
  indent: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_OUTPUT_LEN = 60;

// ---------------------------------------------------------------------------
// Placeholder generators
// ---------------------------------------------------------------------------

function workingPlaceholder(agent: string | null, toolPreview: string | null | undefined): string {
  if (toolPreview) {
    return `working... (${toolPreview})`;
  }
  return "working...";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function OutputLine({
  agent,
  outputText,
  outputAt,
  activityAt,
  isHighlighted,
  isWorking,
  toolPreview,
  indent,
}: OutputLineProps) {
  const fmt = agentColor(agent, isHighlighted ? "highlight" : "normal");
  const boldFmt = agentColor(agent, "highlight");

  if (isWorking) {
    const time = formatRelativeTime(activityAt);
    const placeholder = workingPlaceholder(agent, toolPreview);
    return (
      <Box>
        <Text>{fmt(`${indent}[${time}] out: `)}</Text>
        <Text bold italic>{boldFmt(placeholder)}</Text>
      </Box>
    );
  }

  if (outputText) {
    const truncated = outputText.replace(/\n/g, " ").slice(0, MAX_OUTPUT_LEN);
    const time = formatRelativeTime(outputAt);
    return (
      <Box>
        <Text>{fmt(`${indent}[${time}] out: ${truncated}`)}</Text>
      </Box>
    );
  }

  return null;
}

/**
 * Input highlight line for a session.
 *
 * Shows when the session has received user input (agent hook event).
 * Format: [time]  in: <truncated input text>
 *
 * Source: teleclaude/cli/tui/views/sessions.py (_build_session_row_model, input line)
 */

import React from "react";
import { Box, Text } from "ink";

import { agentColor } from "@/lib/theme/ink-colors.js";
import { formatRelativeTime } from "@/lib/utils/time.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface InputLineProps {
  /** Agent type for theming */
  agent: string;
  /** Raw input text */
  inputText: string;
  /** Input timestamp (ISO string) */
  inputAt: string | null | undefined;
  /** Whether this input is actively highlighted */
  isHighlighted: boolean;
  /** Indent prefix string */
  indent: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_INPUT_LEN = 60;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function InputLine({
  agent,
  inputText,
  inputAt,
  isHighlighted,
  indent,
}: InputLineProps) {
  const truncated = inputText.replace(/\n/g, " ").slice(0, MAX_INPUT_LEN);
  const time = formatRelativeTime(inputAt);
  const fmt = agentColor(agent, isHighlighted ? "highlight" : "normal");

  return (
    <Box>
      <Text>{fmt(`${indent}[${time}]  in: ${truncated}`)}</Text>
    </Box>
  );
}

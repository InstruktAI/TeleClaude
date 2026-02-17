/**
 * Phase status badge for a single build/review phase.
 *
 * Renders a compact indicator like `[B*]` where the letter represents the
 * phase and the symbol represents completion state. Colors are theme-aware
 * using the status color helpers from ink-colors.
 *
 * Source: teleclaude/cli/tui/views/preparation.py (_status_parts, _build_status_block)
 */

import React from "react";
import { Text } from "ink";

import { statusColor, themeText } from "@/lib/theme/ink-colors.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PhaseStatus =
  | "pending"
  | "complete"
  | "approved"
  | "changes_requested"
  | null
  | undefined;

export interface TodoStatusBadgeProps {
  /** Phase abbreviation: B(uild), R(eview), D(ocstrings), S(nippets) */
  phase: "B" | "R" | "D" | "S";
  /** Current status of this phase */
  status: PhaseStatus;
}

// ---------------------------------------------------------------------------
// Status symbol mapping
// ---------------------------------------------------------------------------

function statusSymbol(status: PhaseStatus): string {
  if (!status || status === "pending") return "\u00B7"; // middle dot
  if (status === "complete") return "\u2713"; // check mark
  if (status === "approved") return "\u2713\u2713"; // double check
  if (status === "changes_requested") return "\u26A0"; // warning
  return "\u00B7";
}

function statusFormatter(status: PhaseStatus): (text: string) => string {
  if (!status || status === "pending") return themeText("muted");
  if (status === "complete") return statusColor("ready");
  if (status === "approved") return statusColor("active");
  if (status === "changes_requested") return statusColor("warning");
  return themeText("muted");
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TodoStatusBadge({ phase, status }: TodoStatusBadgeProps) {
  const symbol = statusSymbol(status);
  const fmt = statusFormatter(status);

  return <Text>{fmt(`[${phase}${symbol}]`)}</Text>;
}

/**
 * Subdir path label micro component.
 *
 * Shows the subfolder/worktree path when a session runs in a subdirectory.
 * Strips the "trees/" prefix for cleaner display.
 *
 * Source: teleclaude/cli/tui/views/sessions.py (_build_session_row_model)
 */

import React from "react";
import { Text } from "ink";

import { themeText } from "@/lib/theme/ink-colors.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SubdirProps {
  /** Subdir path (may include "trees/" prefix) */
  path: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Subdir({ path }: SubdirProps) {
  const display = path.replace(/^trees\//, "");
  const fmt = themeText("muted");

  return <Text>{fmt(display)}</Text>;
}

/**
 * Expandable session detail rows below the session header.
 *
 * Shows:
 *   - Activity time, session ID, native session ID
 *
 * Rendered only when the session is not collapsed.
 *
 * Source: teleclaude/cli/tui/views/sessions.py (_build_session_row_model, detail lines)
 */

import React from "react";
import { Box, Text } from "ink";

import { agentColor } from "@/lib/theme/ink-colors.js";
import { formatRelativeTime } from "@/lib/utils/time.js";
import type { SessionInfo } from "@/lib/api/types.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SessionDetailProps {
  /** Session data */
  session: SessionInfo;
  /** Indent prefix string */
  indent: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SessionDetail({ session, indent }: SessionDetailProps) {
  const agent = session.active_agent ?? "?";
  const headerFmt = agentColor(agent, "muted");

  const activityTime = formatRelativeTime(session.last_activity);
  const sessionId = session.session_id;
  const nativeId = session.native_session_id ?? "-";

  const detailLine = `${indent}[${activityTime}] ${sessionId} / ${nativeId}`;

  return (
    <Box>
      <Text>{headerFmt(detailLine)}</Text>
    </Box>
  );
}

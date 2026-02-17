/**
 * Session header row: the main visible line for each session.
 *
 * Layout:
 *   [sticky pin?] [collapse arrow] [Badge] agent/mode [Subdir?] "Title"
 *
 * Selected row uses highlight colors. Headless sessions are dimmed.
 * Previewed sessions get a distinct background tint.
 *
 * Source: teleclaude/cli/tui/views/sessions.py (_build_session_row_model)
 */

import React from "react";
import { Box, Text } from "ink";

import { agentColor } from "@/lib/theme/ink-colors.js";
import type { SessionInfo } from "@/lib/api/types.js";

import { Badge } from "../micro/Badge.js";
import { Subdir } from "../micro/Subdir.js";
import { Title } from "../micro/Title.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SessionHeaderProps {
  /** Session data */
  session: SessionInfo;
  /** Display index string (e.g. "1", "2.1") */
  displayIndex: string;
  /** Whether this row is selected */
  isSelected: boolean;
  /** Whether the session detail is collapsed */
  isCollapsed: boolean;
  /** Sticky pin position (1-based) or null */
  stickyPosition: number | null;
  /** Whether this session is being previewed */
  isPreviewed: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SessionHeader({
  session,
  displayIndex,
  isSelected,
  isCollapsed,
  stickyPosition,
  isPreviewed,
}: SessionHeaderProps) {
  const agent = session.active_agent ?? "?";
  const mode = session.thinking_mode ?? "?";
  const title = session.title;
  const subdir = session.subdir;

  const statusRaw = (session.status ?? "").trim().toLowerCase();
  const isHeadless = statusRaw.startsWith("headless") || !session.tmux_session_name;

  const collapseIndicator = isCollapsed ? "\u25B6" : "\u25BC";

  const colorLevel = isHeadless ? "subtle" : "normal";
  const titleColorLevel = isSelected ? "highlight" : colorLevel;
  const headerFmt = agentColor(agent, colorLevel);
  const selectedFmt = agentColor(agent, titleColorLevel);

  return (
    <Box>
      {/* Sticky badge */}
      {stickyPosition != null && (
        <Text color="yellow" bold={isSelected}>{`[${stickyPosition}]`} </Text>
      )}

      {/* Collapse indicator + agent/mode */}
      <Text bold={isSelected}>
        {selectedFmt(`${collapseIndicator} `)}
      </Text>
      <Badge agent={agent} focused={isSelected} />
      <Text> </Text>
      <Text>{headerFmt(`${agent}/${mode}`)}</Text>

      {/* Subdir (if present) */}
      {subdir && (
        <>
          <Text> </Text>
          <Subdir path={subdir} />
        </>
      )}

      {/* Title */}
      <Text> </Text>
      <Title
        text={title}
        agent={agent}
        selected={isSelected}
        headless={isHeadless}
      />
    </Box>
  );
}

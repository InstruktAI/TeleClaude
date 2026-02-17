/**
 * Session tree node: wrapper that composes SessionHeader, SessionDetail,
 * InputLine, and OutputLine into a complete session row.
 *
 * Collapsed state hides detail lines. Sticky sessions show pin indicators.
 * Input/output highlights are driven by store state.
 *
 * Source: teleclaude/cli/tui/views/sessions.py (_build_session_row_model, _render_session_line)
 */

import React from "react";
import { Box, Text } from "ink";

import type {
  FlatTreeItem,
  SessionNode as SessionNodeType,
} from "@/lib/tree/types.js";
import { treePrefix } from "@/lib/tree/flatten.js";
import type { SessionViewState } from "@/lib/store/types.js";

import { SessionHeader } from "./SessionHeader.js";
import { SessionDetail } from "./SessionDetail.js";
import { InputLine } from "./InputLine.js";
import { OutputLine } from "./OutputLine.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SessionNodeProps {
  /** The flat tree item carrying the session node */
  item: FlatTreeItem;
  /** Whether this row is the currently selected item */
  isSelected: boolean;
  /** Session view state slice (for highlights, collapse, sticky) */
  sessionsState: SessionViewState;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SessionNode({
  item,
  isSelected,
  sessionsState,
}: SessionNodeProps) {
  const node = item.node as SessionNodeType;
  const session = node.data.session;
  const sessionId = session.session_id;
  const prefix = treePrefix(item);

  const isCollapsed = sessionsState.collapsedSessions.has(sessionId);
  const previewSessionId = sessionsState.preview?.sessionId ?? null;
  const isPreviewed = previewSessionId === sessionId
    && !sessionsState.stickySessions.some((s) => s.sessionId === sessionId);

  // Sticky position (1-based)
  const stickyIdx = sessionsState.stickySessions.findIndex(
    (s) => s.sessionId === sessionId,
  );
  const stickyPosition = stickyIdx >= 0 ? stickyIdx + 1 : null;

  // Highlight state
  const hasInputHighlight = sessionsState.inputHighlights.has(sessionId);
  const hasTempOutputHighlight = sessionsState.tempOutputHighlights.has(sessionId);
  const hasOutputHighlight =
    sessionsState.outputHighlights.has(sessionId) || hasTempOutputHighlight;
  const hasActivity = sessionId in sessionsState.lastActivityAt;

  // Determine output working state
  const isOutputWorking =
    hasTempOutputHighlight || hasInputHighlight || (hasOutputHighlight && !sessionsState.lastOutputSummary[sessionId]);

  // Detail indent
  const depthIndent = "  ".repeat(Math.max(0, item.depth - 1));
  const detailIndent = depthIndent + "    ";

  // Agent type for theming
  const agent = session.active_agent ?? "?";

  // Output timestamps
  const eventActivityAt = sessionsState.lastActivityAt[sessionId];
  const summaryAt =
    sessionsState.lastOutputSummaryAt[sessionId] ?? session.last_output_summary_at;
  const outputAt = summaryAt ?? eventActivityAt ?? session.last_activity;

  const lastOutput = sessionsState.lastOutputSummary[sessionId] ?? "";

  return (
    <Box flexDirection="column">
      {/* Header row */}
      <Box>
        <Text dimColor>{prefix}</Text>
        <SessionHeader
          session={session}
          displayIndex={node.data.displayIndex}
          isSelected={isSelected}
          isCollapsed={isCollapsed}
          stickyPosition={stickyPosition}
          isPreviewed={isPreviewed}
        />
      </Box>

      {/* Detail rows (visible when expanded) */}
      {!isCollapsed && (
        <>
          {/* Session ID + activity time */}
          <SessionDetail
            session={session}
            indent={detailIndent}
          />

          {/* Input line */}
          {session.last_input && (
            <InputLine
              agent={agent}
              inputText={session.last_input}
              inputAt={session.last_input_at}
              isHighlighted={hasInputHighlight}
              indent={detailIndent}
            />
          )}

          {/* Output line */}
          <OutputLine
            agent={agent}
            outputText={isOutputWorking ? "" : lastOutput}
            outputAt={outputAt}
            activityAt={eventActivityAt ?? session.last_activity}
            isHighlighted={hasOutputHighlight}
            isWorking={isOutputWorking}
            toolPreview={sessionsState.activeTool[sessionId] ?? null}
            indent={detailIndent}
          />
        </>
      )}
    </Box>
  );
}

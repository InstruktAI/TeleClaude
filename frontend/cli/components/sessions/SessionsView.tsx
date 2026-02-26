/**
 * Main sessions view container for the TeleClaude TUI.
 *
 * The "smart" component that:
 *   - Reads session, computer, and project data from the store
 *   - Builds the hierarchical tree via buildSessionTree
 *   - Flattens it via flattenTree with collapse state
 *   - Manages keyboard navigation, scroll, preview, sticky toggle
 *   - Coordinates modals (start session, confirm end)
 *   - Delegates rendering to TreeContainer
 *
 * Source: teleclaude/cli/tui/views/sessions.py (SessionsView)
 */

import React, { useMemo, useCallback, useState } from "react";
import { Box, Text } from "ink";

import { useTuiStore } from "@/lib/store/index.js";
import { buildSessionTree } from "@/lib/tree/builder.js";
import { flattenTree, collectSessionIds } from "@/lib/tree/flatten.js";
import { themeText } from "@/lib/theme/ink-colors.js";
import type { ComputerInfo, ProjectInfo, SessionInfo } from "@/lib/api/types.js";
import type { FlatTreeItem, SessionNode } from "@/lib/tree/types.js";

import { useKeyBindings } from "../../hooks/useKeyBindings.js";
import { useScrollable } from "../../hooks/useScrollable.js";
import { useDoublePress } from "../../hooks/useDoublePress.js";
import { useTmux } from "../../hooks/useTmux.js";

import { TreeContainer } from "./TreeContainer.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SessionsViewProps {
  /** All known computers */
  computers: ComputerInfo[];
  /** All known projects */
  projects: ProjectInfo[];
  /** All sessions across computers */
  sessions: SessionInfo[];
  /** Viewport height (rows available for the tree) */
  viewportHeight?: number;
  /** Callback when "new session" is requested */
  onNewSession?: () => void;
  /** Callback when "end session" is confirmed for a session ID */
  onEndSession?: (sessionId: string) => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_VIEWPORT_HEIGHT = 20;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SessionsView({
  computers,
  projects,
  sessions,
  viewportHeight = DEFAULT_VIEWPORT_HEIGHT,
  onNewSession,
  onEndSession,
}: SessionsViewProps) {
  const dispatch = useTuiStore((s) => s.dispatch);
  const sessionsState = useTuiStore((s) => s.sessions);

  const {
    selectedIndex,
    scrollOffset,
    collapsedSessions,
    stickySessions,
    preview,
  } = sessionsState;

  // -- Tmux operations -------------------------------------------------------

  const tmux = useTmux();

  // -- Build tree ------------------------------------------------------------

  const stickyIds = useMemo(
    () => new Set(stickySessions.map((s) => s.sessionId)),
    [stickySessions],
  );

  const tree = useMemo(
    () => buildSessionTree(computers, projects, sessions, stickyIds),
    [computers, projects, sessions, stickyIds],
  );

  const flatItems: FlatTreeItem[] = useMemo(
    () => flattenTree(tree, collapsedSessions),
    [tree, collapsedSessions],
  );

  // -- Scrollable navigation -------------------------------------------------

  const scrollable = useScrollable(flatItems.length, viewportHeight);

  // -- Selection helpers -----------------------------------------------------

  const selectedItem = flatItems[selectedIndex] ?? null;

  /**
   * Get the session ID of the currently selected item, if it is a session node.
   */
  const selectedSessionId = useMemo((): string | null => {
    if (!selectedItem) return null;
    if (selectedItem.node.type === "session") {
      return (selectedItem.node as SessionNode).data.session.session_id;
    }
    return null;
  }, [selectedItem]);

  /**
   * Get the agent type of the currently selected session.
   */
  const selectedAgent = useMemo((): string | null => {
    if (!selectedItem) return null;
    if (selectedItem.node.type === "session") {
      return (selectedItem.node as SessionNode).data.session.active_agent ?? null;
    }
    return null;
  }, [selectedItem]);

  const updateSelection = useCallback(
    (newIndex: number) => {
      const clamped = Math.max(0, Math.min(newIndex, flatItems.length - 1));
      dispatch({
        type: "SET_SELECTION",
        view: "sessions",
        index: clamped,
        sessionId: (() => {
          const item = flatItems[clamped];
          if (item?.node.type === "session") {
            return (item.node as SessionNode).data.session.session_id;
          }
          return undefined;
        })(),
        source: "user",
      });

      // Adjust scroll to keep selection visible
      if (clamped < scrollOffset) {
        dispatch({
          type: "SET_SCROLL_OFFSET",
          view: "sessions",
          offset: clamped,
        });
      } else if (clamped >= scrollOffset + viewportHeight) {
        dispatch({
          type: "SET_SCROLL_OFFSET",
          view: "sessions",
          offset: clamped - viewportHeight + 1,
        });
      }
    },
    [dispatch, flatItems, scrollOffset, viewportHeight],
  );

  // -- Double-press for preview / sticky toggle ------------------------------

  const handlePreview = useCallback(
    (sessionId: string) => {
      if (preview?.sessionId === sessionId) {
        dispatch({ type: "CLEAR_PREVIEW" });
        tmux.hidePreview();
      } else {
        dispatch({ type: "SET_PREVIEW", sessionId, activeAgent: selectedAgent });
        tmux.showPreview(sessionId, selectedAgent ?? "claude");
      }
    },
    [dispatch, preview, selectedAgent, tmux],
  );

  const handleToggleSticky = useCallback(
    (sessionId: string) => {
      tmux.toggleSticky(sessionId, selectedAgent ?? "claude");
    },
    [selectedAgent, tmux],
  );

  const { handlePress } = useDoublePress(handlePreview, handleToggleSticky);

  // -- Collapse/expand helpers -----------------------------------------------

  const toggleCollapse = useCallback(
    (sessionId: string) => {
      if (collapsedSessions.has(sessionId)) {
        dispatch({ type: "EXPAND_SESSION", sessionId });
      } else {
        dispatch({ type: "COLLAPSE_SESSION", sessionId });
      }
    },
    [dispatch, collapsedSessions],
  );

  const expandAll = useCallback(() => {
    dispatch({ type: "EXPAND_ALL_SESSIONS" });
  }, [dispatch]);

  const collapseAll = useCallback(() => {
    const sessionIds = collectSessionIds(flatItems);
    dispatch({ type: "COLLAPSE_ALL_SESSIONS", sessionIds });
  }, [dispatch, flatItems]);

  // -- Keyboard bindings -----------------------------------------------------

  useKeyBindings("sessions", {
    navigate_up: () => updateSelection(selectedIndex - 1),
    navigate_down: () => updateSelection(selectedIndex + 1),
    page_up: () => updateSelection(selectedIndex - viewportHeight),
    page_down: () => updateSelection(selectedIndex + viewportHeight),

    space_action: () => {
      if (selectedSessionId) {
        handlePress(selectedSessionId, stickyIds.has(selectedSessionId));
      }
    },

    activate_session: () => {
      if (selectedSessionId) {
        tmux.focusPane(selectedSessionId);
      }
    },

    collapse_or_back: () => {
      if (!selectedItem) return;
      const { node } = selectedItem;

      if (node.type === "session") {
        const sid = (node as SessionNode).data.session.session_id;
        if (!collapsedSessions.has(sid)) {
          toggleCollapse(sid);
        } else if (selectedItem.parentId) {
          // Navigate to parent
          const parentIdx = flatItems.findIndex(
            (fi) => fi.node.id === selectedItem.parentId,
          );
          if (parentIdx >= 0) updateSelection(parentIdx);
        }
        return;
      }

      // For computer/project nodes, navigate to parent
      if (selectedItem.parentId) {
        const parentIdx = flatItems.findIndex(
          (fi) => fi.node.id === selectedItem.parentId,
        );
        if (parentIdx >= 0) updateSelection(parentIdx);
      }
    },

    drill_down: () => {
      if (!selectedItem) return;
      const { node } = selectedItem;

      if (node.type === "session") {
        const sid = (node as SessionNode).data.session.session_id;
        if (collapsedSessions.has(sid)) {
          toggleCollapse(sid);
        }
        return;
      }

      // For computer/project, expand by moving to first child
      if (node.children.length > 0) {
        updateSelection(selectedIndex + 1);
      }
    },

    new_session: () => {
      onNewSession?.();
    },

    kill_session: () => {
      if (selectedSessionId) {
        onEndSession?.(selectedSessionId);
      }
    },

    expand_all: expandAll,
    collapse_all: collapseAll,

    go_back: () => {
      // Clear preview on escape
      if (preview) {
        dispatch({ type: "CLEAR_PREVIEW" });
        tmux.hidePreview();
      }
    },
  });

  // -- Render ----------------------------------------------------------------

  if (sessions.length === 0 && computers.length === 0) {
    const mutedFn = themeText("muted");
    return (
      <Box flexDirection="column" paddingLeft={1} paddingTop={1}>
        <Text>{mutedFn("No sessions found. Press [n] to start one.")}</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      <TreeContainer
        items={flatItems}
        selectedIndex={selectedIndex}
        scrollOffset={scrollOffset}
        viewportHeight={viewportHeight}
        sessionsState={sessionsState}
      />
    </Box>
  );
}

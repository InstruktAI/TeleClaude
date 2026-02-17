/**
 * Tmux pane lifecycle management hook for the TUI.
 *
 * Provides imperative methods for showing/hiding preview panes, toggling
 * sticky sessions into the grid layout, focusing specific panes, and
 * refreshing the layout when the sticky set changes.
 *
 * Polls the active tmux pane every 2 seconds for reverse-sync: when the user
 * clicks a tmux session pane directly, the TUI tree selection follows.
 */

import { useEffect, useRef, useCallback, useState } from "react";

import {
  isTmuxAvailable,
  getCurrentPaneId,
  listPanes,
  selectPane,
  killPane,
  paneExists,
  splitWindow,
  respawnPane,
} from "../lib/tmux.js";
import {
  getLayoutSignature,
  renderLayout,
  type SessionPaneSpec,
} from "../lib/tmux/layout.js";
import { applyPaneColor } from "../lib/tmux/colors.js";
import { tuiStore } from "@/lib/store/index.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PANE_POLL_INTERVAL_MS = 2_000;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UseTmuxResult {
  showPreview: (sessionId: string, agentType: string) => void;
  toggleSticky: (sessionId: string, agentType: string) => void;
  hidePreview: () => void;
  focusPane: (sessionId: string) => void;
  refreshLayout: () => void;
  isInTmux: boolean;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useTmux(): UseTmuxResult {
  const [isInTmux] = useState(() => isTmuxAvailable());

  // Mutable refs for pane tracking (no re-render needed).
  const tuiPaneIdRef = useRef<string>("");
  const previewPaneIdRef = useRef<string | null>(null);
  const previewSessionIdRef = useRef<string | null>(null);
  const stickyPaneMapRef = useRef<Map<string, string>>(new Map());
  const layoutSignatureRef = useRef<string>("");
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Capture the TUI pane ID on mount.
  useEffect(() => {
    if (isInTmux) {
      tuiPaneIdRef.current = getCurrentPaneId();
    }
  }, [isInTmux]);

  // -- Pane command builder -------------------------------------------------

  const buildAttachCommand = useCallback(
    (sessionId: string, agentType: string): string => {
      // Attach to the session's tmux session. The tmux_session_name is
      // typically the session_id itself or a derivative. We use a basic
      // read-only attach so the user sees the agent's terminal output.
      const tmuxSession = sessionId;
      const binary = process.env.TMUX_BINARY || "tmux";
      return `${binary} attach-session -t ${tmuxSession} -r 2>/dev/null || echo 'Session unavailable'; sleep 2`;
    },
    [],
  );

  // -- Layout rebuild -------------------------------------------------------

  const rebuildLayout = useCallback(() => {
    if (!isInTmux || !tuiPaneIdRef.current) return;

    const state = tuiStore.getState();
    const stickySessions = state.sessions.stickySessions;
    const stickyIds = stickySessions.map((s) => s.sessionId);
    const previewId = previewSessionIdRef.current;

    // Check signature to avoid unnecessary rebuilds.
    const sig = getLayoutSignature(stickyIds, previewId);
    if (sig === layoutSignatureRef.current) return;

    // Build session pane specs: sticky first, then preview.
    const specs: SessionPaneSpec[] = [];

    for (const sid of stickyIds) {
      specs.push({
        sessionId: sid,
        command: buildAttachCommand(sid, "claude"),
        isSticky: true,
      });
    }

    if (previewId && !stickyIds.includes(previewId)) {
      specs.push({
        sessionId: previewId,
        command: buildAttachCommand(previewId, "claude"),
        isSticky: false,
      });
    }

    // Collect existing pane IDs to clean up.
    const existingPanes: string[] = [];
    for (const paneId of stickyPaneMapRef.current.values()) {
      existingPanes.push(paneId);
    }
    if (previewPaneIdRef.current) {
      existingPanes.push(previewPaneIdRef.current);
    }

    if (specs.length === 0) {
      // No session panes needed; just clean up.
      for (const paneId of existingPanes) {
        if (paneExists(paneId)) killPane(paneId);
      }
      stickyPaneMapRef.current.clear();
      previewPaneIdRef.current = null;
      layoutSignatureRef.current = sig;
      return;
    }

    const result = renderLayout(tuiPaneIdRef.current, specs, existingPanes);
    if (!result) return;

    // Update tracking maps.
    stickyPaneMapRef.current.clear();
    previewPaneIdRef.current = null;

    for (const [sessionId, paneId] of result.paneMap) {
      if (stickyIds.includes(sessionId)) {
        stickyPaneMapRef.current.set(sessionId, paneId);
      } else {
        previewPaneIdRef.current = paneId;
      }

      // Apply agent colors.
      applyPaneColor(paneId, "claude", sessionId);
    }

    layoutSignatureRef.current = sig;

    // Re-focus the TUI pane after layout changes.
    selectPane(tuiPaneIdRef.current);
  }, [isInTmux, buildAttachCommand]);

  // -- Public API -----------------------------------------------------------

  const showPreview = useCallback(
    (sessionId: string, agentType: string) => {
      if (!isInTmux) return;
      previewSessionIdRef.current = sessionId;

      // If there's already a preview pane and it's alive, respawn it.
      if (previewPaneIdRef.current && paneExists(previewPaneIdRef.current)) {
        respawnPane(
          previewPaneIdRef.current,
          buildAttachCommand(sessionId, agentType),
        );
        applyPaneColor(
          previewPaneIdRef.current,
          agentType,
          sessionId,
        );
        return;
      }

      // Otherwise rebuild the layout to include the new preview.
      rebuildLayout();
    },
    [isInTmux, buildAttachCommand, rebuildLayout],
  );

  const toggleSticky = useCallback(
    (sessionId: string, agentType: string) => {
      if (!isInTmux) return;
      const dispatch = tuiStore.getState().dispatch;
      dispatch({ type: "TOGGLE_STICKY", sessionId, activeAgent: agentType });

      // If this was the preview, clear it (it is now sticky or removed).
      if (previewSessionIdRef.current === sessionId) {
        previewSessionIdRef.current = null;
      }

      rebuildLayout();
    },
    [isInTmux, rebuildLayout],
  );

  const hidePreview = useCallback(() => {
    if (!isInTmux) return;

    previewSessionIdRef.current = null;

    if (previewPaneIdRef.current && paneExists(previewPaneIdRef.current)) {
      killPane(previewPaneIdRef.current);
    }
    previewPaneIdRef.current = null;

    rebuildLayout();
  }, [isInTmux, rebuildLayout]);

  const focusPane = useCallback(
    (sessionId: string) => {
      if (!isInTmux) return;

      // Check sticky panes first.
      const stickyPaneId = stickyPaneMapRef.current.get(sessionId);
      if (stickyPaneId && paneExists(stickyPaneId)) {
        selectPane(stickyPaneId);
        return;
      }

      // Fall back to preview pane.
      if (
        previewSessionIdRef.current === sessionId &&
        previewPaneIdRef.current &&
        paneExists(previewPaneIdRef.current)
      ) {
        selectPane(previewPaneIdRef.current);
      }
    },
    [isInTmux],
  );

  const refreshLayout = useCallback(() => {
    // Force signature invalidation to trigger a full rebuild.
    layoutSignatureRef.current = "";
    rebuildLayout();
  }, [rebuildLayout]);

  // -- Active pane polling for reverse sync ---------------------------------

  useEffect(() => {
    if (!isInTmux) return;

    pollTimerRef.current = setInterval(() => {
      const panes = listPanes();
      const activePane = panes.find((p) => p.active);
      if (!activePane || activePane.id === tuiPaneIdRef.current) return;

      // Find which session this pane belongs to.
      for (const [sessionId, paneId] of stickyPaneMapRef.current) {
        if (paneId === activePane.id) {
          tuiStore.getState().dispatch({
            type: "SET_SELECTION_METHOD",
            method: "pane",
          });
          // Selection index is unknown here; let the view reconcile.
          break;
        }
      }

      if (previewPaneIdRef.current === activePane.id && previewSessionIdRef.current) {
        tuiStore.getState().dispatch({
          type: "SET_SELECTION_METHOD",
          method: "pane",
        });
      }
    }, PANE_POLL_INTERVAL_MS);

    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [isInTmux]);

  // -- Cleanup all panes on unmount -----------------------------------------

  useEffect(() => {
    return () => {
      for (const paneId of stickyPaneMapRef.current.values()) {
        if (paneExists(paneId)) killPane(paneId);
      }
      stickyPaneMapRef.current.clear();

      if (previewPaneIdRef.current && paneExists(previewPaneIdRef.current)) {
        killPane(previewPaneIdRef.current);
      }
      previewPaneIdRef.current = null;
    };
  }, []);

  return {
    showPreview,
    toggleSticky,
    hidePreview,
    focusPane,
    refreshLayout,
    isInTmux,
  };
}

/**
 * Pure reducer porting all intents from Python's reduce_state.
 *
 * Uses Immer's produce() so handlers can write mutating syntax
 * while producing immutable snapshots.
 *
 * Source: teleclaude/cli/tui/state.py  reduce_state()
 */

import { produce } from "immer";

import type { Intent, TuiState } from "./types";
import { MAX_STICKY_PANES } from "./types";

// ---------------------------------------------------------------------------
// Helpers (ported from Python module-level functions)
// ---------------------------------------------------------------------------

function stickyCount(state: TuiState): number {
  return state.sessions.stickySessions.length;
}

/** Keep output highlight on selection-driven view actions for Codex only. */
function preserveOutputHighlightOnSelect(
  activeAgent: string | null | undefined,
): boolean {
  return (activeAgent ?? "").trim().toLowerCase() === "codex";
}

// ---------------------------------------------------------------------------
// Set helpers — Immer drafts wrap Sets; these work on draft.Set instances.
// ---------------------------------------------------------------------------

function setDelete(s: Set<string>, v: string): void {
  s.delete(v);
}

function setAdd(s: Set<string>, v: string): void {
  s.add(v);
}

function setIntersect(s: Set<string>, keep: Set<string>): void {
  for (const v of s) {
    if (!keep.has(v)) {
      s.delete(v);
    }
  }
}

// ---------------------------------------------------------------------------
// Record helpers — prune keys not in a set
// ---------------------------------------------------------------------------

function pruneRecord(
  rec: Record<string, string>,
  keep: Set<string>,
): void {
  for (const key of Object.keys(rec)) {
    if (!keep.has(key)) {
      delete rec[key];
    }
  }
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

export function reduce(state: TuiState, intent: Intent): TuiState {
  return produce(state, (draft) => {
    switch (intent.type) {
      // ---------------------------------------------------------------
      // SET_PREVIEW
      // ---------------------------------------------------------------
      case "SET_PREVIEW": {
        const { sessionId, activeAgent } = intent;
        if (!sessionId) return;
        if (stickyCount(draft) >= MAX_STICKY_PANES) return;
        draft.sessions.preview = { sessionId };
        draft.preparation.preview = null;
        if (!preserveOutputHighlightOnSelect(activeAgent)) {
          setDelete(draft.sessions.outputHighlights, sessionId);
        }
        return;
      }

      // ---------------------------------------------------------------
      // CLEAR_PREVIEW
      // ---------------------------------------------------------------
      case "CLEAR_PREVIEW": {
        draft.sessions.preview = null;
        return;
      }

      // ---------------------------------------------------------------
      // TOGGLE_STICKY
      // ---------------------------------------------------------------
      case "TOGGLE_STICKY": {
        const { sessionId, activeAgent } = intent;
        if (!sessionId) return;
        const existingIdx = draft.sessions.stickySessions.findIndex(
          (s) => s.sessionId === sessionId,
        );
        if (existingIdx !== -1) {
          // Remove existing sticky
          draft.sessions.stickySessions.splice(existingIdx, 1);
        } else {
          // Add new sticky
          if (stickyCount(draft) >= MAX_STICKY_PANES) return;
          draft.sessions.stickySessions.push({ sessionId });
          // Clear preview if this session was being previewed
          if (
            draft.sessions.preview &&
            draft.sessions.preview.sessionId === sessionId
          ) {
            draft.sessions.preview = null;
          }
          if (!preserveOutputHighlightOnSelect(activeAgent)) {
            setDelete(draft.sessions.outputHighlights, sessionId);
          }
        }
        return;
      }

      // ---------------------------------------------------------------
      // SET_PREP_PREVIEW
      // ---------------------------------------------------------------
      case "SET_PREP_PREVIEW": {
        const { docId, command, title } = intent;
        if (!docId || !command) return;
        if (stickyCount(draft) >= MAX_STICKY_PANES) return;
        draft.preparation.preview = {
          docId,
          command,
          title: title ?? "",
        };
        draft.sessions.preview = null;
        return;
      }

      // ---------------------------------------------------------------
      // CLEAR_PREP_PREVIEW
      // ---------------------------------------------------------------
      case "CLEAR_PREP_PREVIEW": {
        draft.preparation.preview = null;
        return;
      }

      // ---------------------------------------------------------------
      // COLLAPSE_SESSION
      // ---------------------------------------------------------------
      case "COLLAPSE_SESSION": {
        const { sessionId } = intent;
        if (sessionId) {
          setAdd(draft.sessions.collapsedSessions, sessionId);
        }
        return;
      }

      // ---------------------------------------------------------------
      // EXPAND_SESSION
      // ---------------------------------------------------------------
      case "EXPAND_SESSION": {
        const { sessionId } = intent;
        if (sessionId && draft.sessions.collapsedSessions.has(sessionId)) {
          setDelete(draft.sessions.collapsedSessions, sessionId);
        }
        return;
      }

      // ---------------------------------------------------------------
      // EXPAND_ALL_SESSIONS
      // ---------------------------------------------------------------
      case "EXPAND_ALL_SESSIONS": {
        draft.sessions.collapsedSessions.clear();
        return;
      }

      // ---------------------------------------------------------------
      // COLLAPSE_ALL_SESSIONS
      // ---------------------------------------------------------------
      case "COLLAPSE_ALL_SESSIONS": {
        draft.sessions.collapsedSessions = new Set(intent.sessionIds);
        return;
      }

      // ---------------------------------------------------------------
      // EXPAND_TODO
      // ---------------------------------------------------------------
      case "EXPAND_TODO": {
        const { todoId } = intent;
        if (todoId) {
          setAdd(draft.preparation.expandedTodos, todoId);
        }
        return;
      }

      // ---------------------------------------------------------------
      // COLLAPSE_TODO
      // ---------------------------------------------------------------
      case "COLLAPSE_TODO": {
        const { todoId } = intent;
        if (todoId) {
          setDelete(draft.preparation.expandedTodos, todoId);
        }
        return;
      }

      // ---------------------------------------------------------------
      // EXPAND_ALL_TODOS
      // ---------------------------------------------------------------
      case "EXPAND_ALL_TODOS": {
        for (const id of intent.todoIds) {
          setAdd(draft.preparation.expandedTodos, id);
        }
        return;
      }

      // ---------------------------------------------------------------
      // COLLAPSE_ALL_TODOS
      // ---------------------------------------------------------------
      case "COLLAPSE_ALL_TODOS": {
        draft.preparation.expandedTodos.clear();
        return;
      }

      // ---------------------------------------------------------------
      // SET_SELECTION
      // ---------------------------------------------------------------
      case "SET_SELECTION": {
        const { view, index, sessionId, source, activeAgent } = intent;
        if (view === "sessions" && typeof index === "number") {
          const prevSessionId = draft.sessions.selectedSessionId;
          draft.sessions.selectedIndex = index;
          if (typeof sessionId === "string") {
            draft.sessions.selectedSessionId = sessionId;
            draft.sessions.lastSelectionSessionId = sessionId;
            if (
              source === "user" ||
              source === "pane" ||
              source === "system"
            ) {
              draft.sessions.lastSelectionSource = source;
            }
            if (
              (source === "user" || source === "pane") &&
              prevSessionId &&
              sessionId !== prevSessionId &&
              !preserveOutputHighlightOnSelect(activeAgent)
            ) {
              setDelete(draft.sessions.outputHighlights, sessionId);
            }
          }
        }
        if (view === "preparation" && typeof index === "number") {
          draft.preparation.selectedIndex = index;
        }
        return;
      }

      // ---------------------------------------------------------------
      // SET_SCROLL_OFFSET
      // ---------------------------------------------------------------
      case "SET_SCROLL_OFFSET": {
        const { view, offset } = intent;
        if (view === "sessions" && typeof offset === "number") {
          draft.sessions.scrollOffset = offset;
        }
        if (view === "preparation" && typeof offset === "number") {
          draft.preparation.scrollOffset = offset;
        }
        return;
      }

      // ---------------------------------------------------------------
      // SET_SELECTION_METHOD
      // ---------------------------------------------------------------
      case "SET_SELECTION_METHOD": {
        const { method } = intent;
        if (
          method === "arrow" ||
          method === "click" ||
          method === "pane"
        ) {
          draft.sessions.selectionMethod = method;
        }
        return;
      }

      // ---------------------------------------------------------------
      // SESSION_ACTIVITY (legacy event-based highlights)
      // ---------------------------------------------------------------
      case "SESSION_ACTIVITY": {
        const { sessionId, reason } = intent;
        if (!sessionId) return;
        if (reason === "user_input") {
          setAdd(draft.sessions.inputHighlights, sessionId);
          setDelete(draft.sessions.outputHighlights, sessionId);
          setDelete(draft.sessions.tempOutputHighlights, sessionId);
        } else if (reason === "tool_done") {
          setDelete(draft.sessions.inputHighlights, sessionId);
          setDelete(draft.sessions.outputHighlights, sessionId);
          setAdd(draft.sessions.tempOutputHighlights, sessionId);
        } else if (reason === "agent_stopped") {
          setDelete(draft.sessions.inputHighlights, sessionId);
          setDelete(draft.sessions.tempOutputHighlights, sessionId);
          setAdd(draft.sessions.outputHighlights, sessionId);
        }
        // "state_change" reason: no highlight changes
        return;
      }

      // ---------------------------------------------------------------
      // AGENT_ACTIVITY (hook-based highlights with tool tracking)
      // ---------------------------------------------------------------
      case "AGENT_ACTIVITY": {
        const { sessionId, eventType, toolName, toolPreview, summary, timestamp } =
          intent;
        if (!sessionId || !eventType) return;

        // Store activity timestamp from every event type
        if (typeof timestamp === "string" && timestamp) {
          draft.sessions.lastActivityAt[sessionId] = timestamp;
        }

        if (eventType === "user_prompt_submit") {
          setAdd(draft.sessions.inputHighlights, sessionId);
          setDelete(draft.sessions.outputHighlights, sessionId);
          setDelete(draft.sessions.tempOutputHighlights, sessionId);
        } else if (eventType === "tool_use") {
          setDelete(draft.sessions.inputHighlights, sessionId);
          setAdd(draft.sessions.tempOutputHighlights, sessionId);
          setAdd(draft.sessions.activityTimerReset, sessionId);
          let toolLabel: string | null = null;
          if (typeof toolPreview === "string" && toolPreview) {
            toolLabel = toolPreview;
          } else if (typeof toolName === "string" && toolName) {
            toolLabel = toolName;
          }
          if (toolLabel) {
            draft.sessions.activeTool[sessionId] = toolLabel;
          }
        } else if (eventType === "tool_done") {
          setDelete(draft.sessions.inputHighlights, sessionId);
          setAdd(draft.sessions.tempOutputHighlights, sessionId);
          setAdd(draft.sessions.activityTimerReset, sessionId);
          delete draft.sessions.activeTool[sessionId];
        } else if (eventType === "agent_stop") {
          setDelete(draft.sessions.inputHighlights, sessionId);
          setDelete(draft.sessions.tempOutputHighlights, sessionId);
          delete draft.sessions.activeTool[sessionId];
          setAdd(draft.sessions.outputHighlights, sessionId);
          if (typeof summary === "string" && summary) {
            draft.sessions.lastOutputSummary[sessionId] = summary;
          }
          if (typeof timestamp === "string" && timestamp) {
            draft.sessions.lastOutputSummaryAt[sessionId] = timestamp;
          }
        }
        return;
      }

      // ---------------------------------------------------------------
      // CLEAR_TEMP_HIGHLIGHT
      // ---------------------------------------------------------------
      case "CLEAR_TEMP_HIGHLIGHT": {
        const { sessionId } = intent;
        if (sessionId) {
          setDelete(draft.sessions.tempOutputHighlights, sessionId);
          // Safety-net: clear stale tool placeholder, keep output highlighted
          delete draft.sessions.activeTool[sessionId];
          setAdd(draft.sessions.outputHighlights, sessionId);
        }
        return;
      }

      // ---------------------------------------------------------------
      // SYNC_SESSIONS
      // ---------------------------------------------------------------
      case "SYNC_SESSIONS": {
        const sessionIdSet = new Set(intent.sessionIds);

        // Prune preview if session no longer exists
        if (
          draft.sessions.preview &&
          !sessionIdSet.has(draft.sessions.preview.sessionId)
        ) {
          draft.sessions.preview = null;
        }

        // Prune sticky sessions
        if (draft.sessions.stickySessions.length > 0) {
          draft.sessions.stickySessions =
            draft.sessions.stickySessions.filter((s) =>
              sessionIdSet.has(s.sessionId),
            );
        }

        // Intersect all Set-based collections with live session IDs
        setIntersect(draft.sessions.collapsedSessions, sessionIdSet);
        setIntersect(draft.sessions.inputHighlights, sessionIdSet);
        setIntersect(draft.sessions.outputHighlights, sessionIdSet);
        setIntersect(draft.sessions.tempOutputHighlights, sessionIdSet);
        setIntersect(draft.sessions.activityTimerReset, sessionIdSet);

        // Prune Record-based collections
        pruneRecord(draft.sessions.lastOutputSummary, sessionIdSet);
        pruneRecord(draft.sessions.lastOutputSummaryAt, sessionIdSet);
        pruneRecord(draft.sessions.lastActivityAt, sessionIdSet);
        return;
      }

      // ---------------------------------------------------------------
      // SYNC_TODOS
      // ---------------------------------------------------------------
      case "SYNC_TODOS": {
        const todoIdSet = new Set(intent.todoIds);
        setIntersect(draft.preparation.expandedTodos, todoIdSet);
        return;
      }

      // ---------------------------------------------------------------
      // SET_FILE_PANE_ID
      // ---------------------------------------------------------------
      case "SET_FILE_PANE_ID": {
        if (typeof intent.paneId === "string") {
          draft.preparation.filePaneId = intent.paneId;
        }
        return;
      }

      // ---------------------------------------------------------------
      // CLEAR_FILE_PANE_ID
      // ---------------------------------------------------------------
      case "CLEAR_FILE_PANE_ID": {
        draft.preparation.filePaneId = null;
        return;
      }

      // ---------------------------------------------------------------
      // SET_ANIMATION_MODE
      // ---------------------------------------------------------------
      case "SET_ANIMATION_MODE": {
        const { mode } = intent;
        if (mode === "off" || mode === "periodic" || mode === "party") {
          draft.animationMode = mode;
        }
        return;
      }

      // ---------------------------------------------------------------
      // SET_CONFIG_SUBTAB
      // ---------------------------------------------------------------
      case "SET_CONFIG_SUBTAB": {
        const { subtab } = intent;
        if (
          subtab === "adapters" ||
          subtab === "people" ||
          subtab === "notifications" ||
          subtab === "environment" ||
          subtab === "validate"
        ) {
          draft.config.activeSubtab = subtab;
        }
        return;
      }

      // ---------------------------------------------------------------
      // SET_CONFIG_GUIDED_MODE
      // ---------------------------------------------------------------
      case "SET_CONFIG_GUIDED_MODE": {
        if (typeof intent.enabled === "boolean") {
          draft.config.guidedMode = intent.enabled;
        }
        return;
      }

      default: {
        // Exhaustiveness check: TypeScript will error if a case is missing
        const _exhaustive: never = intent;
        void _exhaustive;
        return;
      }
    }
  });
}

/**
 * Derived state selectors.
 *
 * All selectors are pure functions of TuiState, making them
 * trivially memoizable with useMemo or Zustand's shallow equality.
 */

import type { TuiState } from "./types";

// ---------------------------------------------------------------------------
// Session selectors
// ---------------------------------------------------------------------------

/** Ordered list of sticky session IDs. */
export function selectStickyIds(state: TuiState): string[] {
  return state.sessions.stickySessions.map((s) => s.sessionId);
}

/** Set of session IDs that have any highlight (input, output, or temp). */
export function selectHighlightedSessions(state: TuiState): Set<string> {
  const result = new Set<string>();
  for (const id of state.sessions.inputHighlights) {
    result.add(id);
  }
  for (const id of state.sessions.outputHighlights) {
    result.add(id);
  }
  for (const id of state.sessions.tempOutputHighlights) {
    result.add(id);
  }
  return result;
}

/** Session IDs with pending input highlights (user waiting for response). */
export function selectInputHighlightedSessions(state: TuiState): Set<string> {
  return state.sessions.inputHighlights;
}

/** Session IDs with completed output highlights (agent finished). */
export function selectOutputHighlightedSessions(state: TuiState): Set<string> {
  return state.sessions.outputHighlights;
}

/** Session IDs with temporary output highlights (agent working). */
export function selectTempHighlightedSessions(state: TuiState): Set<string> {
  return state.sessions.tempOutputHighlights;
}

/** Session IDs needing activity timer reset (for streaming safety timer). */
export function selectTimerResetSessions(state: TuiState): Set<string> {
  return state.sessions.activityTimerReset;
}

/** Active tool label for a given session, or null. */
export function selectActiveTool(
  state: TuiState,
  sessionId: string,
): string | null {
  return state.sessions.activeTool[sessionId] ?? null;
}

/** Output summary for a given session, or null. */
export function selectOutputSummary(
  state: TuiState,
  sessionId: string,
): string | null {
  return state.sessions.lastOutputSummary[sessionId] ?? null;
}

/** Output summary timestamp for a given session, or null. */
export function selectOutputSummaryAt(
  state: TuiState,
  sessionId: string,
): string | null {
  return state.sessions.lastOutputSummaryAt[sessionId] ?? null;
}

/** Last activity timestamp for a given session, or null. */
export function selectLastActivityAt(
  state: TuiState,
  sessionId: string,
): string | null {
  return state.sessions.lastActivityAt[sessionId] ?? null;
}

/** Currently previewed session ID, or null. */
export function selectPreviewSessionId(state: TuiState): string | null {
  return state.sessions.preview?.sessionId ?? null;
}

/** Whether a specific session is collapsed in the tree view. */
export function selectIsSessionCollapsed(
  state: TuiState,
  sessionId: string,
): boolean {
  return state.sessions.collapsedSessions.has(sessionId);
}

/** All session IDs that are visible in a pane (preview + sticky). */
export function selectPaneSessions(state: TuiState): string[] {
  const result: string[] = [];
  if (state.sessions.preview) {
    result.push(state.sessions.preview.sessionId);
  }
  for (const sticky of state.sessions.stickySessions) {
    if (
      !state.sessions.preview ||
      sticky.sessionId !== state.sessions.preview.sessionId
    ) {
      result.push(sticky.sessionId);
    }
  }
  return result;
}

/** Number of occupied pane slots (preview counts as one). */
export function selectPaneCount(state: TuiState): number {
  let count = state.sessions.stickySessions.length;
  if (state.sessions.preview) {
    count += 1;
  }
  return count;
}

// ---------------------------------------------------------------------------
// Preparation selectors
// ---------------------------------------------------------------------------

/** Whether a todo item is expanded. */
export function selectIsTodoExpanded(
  state: TuiState,
  todoId: string,
): boolean {
  return state.preparation.expandedTodos.has(todoId);
}

/** All expanded todo IDs. */
export function selectExpandedTodoIds(state: TuiState): Set<string> {
  return state.preparation.expandedTodos;
}

/** Currently previewed document info, or null. */
export function selectDocPreview(state: TuiState) {
  return state.preparation.preview;
}

/** Active file pane ID, or null. */
export function selectFilePaneId(state: TuiState): string | null {
  return state.preparation.filePaneId;
}

// ---------------------------------------------------------------------------
// Config selectors
// ---------------------------------------------------------------------------

/** Active configuration subtab. */
export function selectConfigSubtab(state: TuiState) {
  return state.config.activeSubtab;
}

/** Whether guided mode is enabled. */
export function selectGuidedMode(state: TuiState): boolean {
  return state.config.guidedMode;
}

// ---------------------------------------------------------------------------
// Global selectors
// ---------------------------------------------------------------------------

/** Current animation mode. */
export function selectAnimationMode(state: TuiState) {
  return state.animationMode;
}

/** Current selected index for a given view. */
export function selectSelectedIndex(
  state: TuiState,
  view: "sessions" | "preparation",
): number {
  if (view === "sessions") return state.sessions.selectedIndex;
  return state.preparation.selectedIndex;
}

/** Current scroll offset for a given view. */
export function selectScrollOffset(
  state: TuiState,
  view: "sessions" | "preparation",
): number {
  if (view === "sessions") return state.sessions.scrollOffset;
  return state.preparation.scrollOffset;
}

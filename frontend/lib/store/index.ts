/**
 * Zustand store for TUI state management.
 *
 * The reducer already uses Immer's produce() for immutable updates,
 * so the store itself does not need the immer middleware.
 *
 * Provides both:
 * - `useTuiStore` hook for React/Ink components
 * - `tuiStore` vanilla store for WebSocket handlers and non-React code
 */

import { create } from "zustand";

import { reduce } from "./reducer";
import type { Intent, TuiStore } from "./types";

// ---------------------------------------------------------------------------
// Initial state factory
// ---------------------------------------------------------------------------

function createInitialState() {
  return {
    sessions: {
      selectedIndex: 0,
      selectedSessionId: null as string | null,
      lastSelectionSource: "system" as const,
      lastSelectionSessionId: null as string | null,
      scrollOffset: 0,
      selectionMethod: "arrow" as const,
      collapsedSessions: new Set<string>(),
      stickySessions: [] as { sessionId: string }[],
      preview: null,
      inputHighlights: new Set<string>(),
      outputHighlights: new Set<string>(),
      tempOutputHighlights: new Set<string>(),
      activeTool: {} as Record<string, string>,
      activityTimerReset: new Set<string>(),
      lastOutputSummary: {} as Record<string, string>,
      lastOutputSummaryAt: {} as Record<string, string>,
      lastActivityAt: {} as Record<string, string>,
    },
    preparation: {
      selectedIndex: 0,
      scrollOffset: 0,
      expandedTodos: new Set<string>(),
      filePaneId: null as string | null,
      preview: null,
    },
    config: {
      activeSubtab: "adapters" as const,
      guidedMode: false,
    },
    animationMode: "periodic" as const,
  };
}

// ---------------------------------------------------------------------------
// Store creation
// ---------------------------------------------------------------------------

export const useTuiStore = create<TuiStore>()((set, get) => ({
  ...createInitialState(),

  dispatch: (intent: Intent) => {
    const { dispatch: _, ...currentState } = get();
    const nextState = reduce(currentState, intent);
    set(nextState);
  },
}));

/**
 * Vanilla (non-React) store reference.
 *
 * Use this from WebSocket event handlers, timers, or any code
 * that runs outside the React tree.
 *
 * Examples:
 *   tuiStore.getState().dispatch({ type: "SYNC_SESSIONS", sessionIds: [...] })
 *   tuiStore.subscribe((state) => persist(state))
 */
export const tuiStore = useTuiStore;

// Re-export types for convenience
export type { Intent, TuiState, TuiStore } from "./types";

/**
 * TUI State types and Intent discriminated union.
 *
 * Faithful port of:
 * - teleclaude/cli/tui/state.py (TuiState, IntentType, IntentPayload)
 * - teleclaude/cli/tui/types.py (StickySessionInfo, TodoStatus, etc.)
 */

// ---------------------------------------------------------------------------
// Domain types (local until reconciled with WI-01)
// ---------------------------------------------------------------------------

export interface StickySessionInfo {
  sessionId: string;
}

export interface PreviewState {
  sessionId: string;
}

export interface DocPreviewState {
  docId: string;
  command: string;
  title: string;
}

export type AnimationMode = "off" | "periodic" | "party";
export type SelectionMethod = "arrow" | "click" | "pane";
export type SelectionSource = "user" | "pane" | "system";
export type ConfigSubtab =
  | "adapters"
  | "people"
  | "notifications"
  | "environment"
  | "validate";

export type AgentHookEventType =
  | "user_prompt_submit"
  | "tool_use"
  | "tool_done"
  | "agent_stop";

// ---------------------------------------------------------------------------
// View state interfaces
// ---------------------------------------------------------------------------

export interface SessionViewState {
  selectedIndex: number;
  selectedSessionId: string | null;
  lastSelectionSource: SelectionSource;
  lastSelectionSessionId: string | null;
  scrollOffset: number;
  selectionMethod: SelectionMethod;
  collapsedSessions: Set<string>;
  stickySessions: StickySessionInfo[];
  preview: PreviewState | null;
  inputHighlights: Set<string>;
  outputHighlights: Set<string>;
  tempOutputHighlights: Set<string>;
  activeTool: Record<string, string>; // sessionId -> tool preview text
  activityTimerReset: Set<string>;
  lastOutputSummary: Record<string, string>; // sessionId -> summary
  lastOutputSummaryAt: Record<string, string>; // sessionId -> ISO timestamp
  lastActivityAt: Record<string, string>; // sessionId -> ISO timestamp
}

export interface PreparationViewState {
  selectedIndex: number;
  scrollOffset: number;
  expandedTodos: Set<string>;
  filePaneId: string | null;
  preview: DocPreviewState | null;
}

export interface ConfigViewState {
  activeSubtab: ConfigSubtab;
  guidedMode: boolean;
}

// ---------------------------------------------------------------------------
// Root TUI state
// ---------------------------------------------------------------------------

export interface TuiState {
  sessions: SessionViewState;
  preparation: PreparationViewState;
  config: ConfigViewState;
  animationMode: AnimationMode;
}

// ---------------------------------------------------------------------------
// Intent types (discriminated union)
// ---------------------------------------------------------------------------

export interface SetPreviewIntent {
  type: "SET_PREVIEW";
  sessionId: string;
  activeAgent?: string | null;
}

export interface ClearPreviewIntent {
  type: "CLEAR_PREVIEW";
}

export interface ToggleStickyIntent {
  type: "TOGGLE_STICKY";
  sessionId: string;
  activeAgent?: string | null;
}

export interface SetPrepPreviewIntent {
  type: "SET_PREP_PREVIEW";
  docId: string;
  command: string;
  title?: string;
}

export interface ClearPrepPreviewIntent {
  type: "CLEAR_PREP_PREVIEW";
}

export interface CollapseSessionIntent {
  type: "COLLAPSE_SESSION";
  sessionId: string;
}

export interface ExpandSessionIntent {
  type: "EXPAND_SESSION";
  sessionId: string;
}

export interface ExpandAllSessionsIntent {
  type: "EXPAND_ALL_SESSIONS";
}

export interface CollapseAllSessionsIntent {
  type: "COLLAPSE_ALL_SESSIONS";
  sessionIds: string[];
}

export interface ExpandTodoIntent {
  type: "EXPAND_TODO";
  todoId: string;
}

export interface CollapseTodoIntent {
  type: "COLLAPSE_TODO";
  todoId: string;
}

export interface ExpandAllTodosIntent {
  type: "EXPAND_ALL_TODOS";
  todoIds: string[];
}

export interface CollapseAllTodosIntent {
  type: "COLLAPSE_ALL_TODOS";
}

export interface SetSelectionIntent {
  type: "SET_SELECTION";
  view: "sessions" | "preparation";
  index: number;
  sessionId?: string;
  source?: SelectionSource;
  activeAgent?: string | null;
}

export interface SetScrollOffsetIntent {
  type: "SET_SCROLL_OFFSET";
  view: "sessions" | "preparation";
  offset: number;
}

export interface SetSelectionMethodIntent {
  type: "SET_SELECTION_METHOD";
  method: SelectionMethod;
}

export interface SessionActivityIntent {
  type: "SESSION_ACTIVITY";
  sessionId: string;
  reason: "user_input" | "tool_done" | "agent_stopped" | "state_change";
}

export interface AgentActivityIntent {
  type: "AGENT_ACTIVITY";
  sessionId: string;
  eventType: AgentHookEventType;
  toolName?: string | null;
  toolPreview?: string | null;
  summary?: string | null;
  timestamp?: string;
}

export interface ClearTempHighlightIntent {
  type: "CLEAR_TEMP_HIGHLIGHT";
  sessionId: string;
}

export interface SyncSessionsIntent {
  type: "SYNC_SESSIONS";
  sessionIds: string[];
}

export interface SyncTodosIntent {
  type: "SYNC_TODOS";
  todoIds: string[];
}

export interface SetFilePaneIdIntent {
  type: "SET_FILE_PANE_ID";
  paneId: string;
}

export interface ClearFilePaneIdIntent {
  type: "CLEAR_FILE_PANE_ID";
}

export interface SetAnimationModeIntent {
  type: "SET_ANIMATION_MODE";
  mode: AnimationMode;
}

export interface SetConfigSubtabIntent {
  type: "SET_CONFIG_SUBTAB";
  subtab: ConfigSubtab;
}

export interface SetConfigGuidedModeIntent {
  type: "SET_CONFIG_GUIDED_MODE";
  enabled: boolean;
}

export type Intent =
  | SetPreviewIntent
  | ClearPreviewIntent
  | ToggleStickyIntent
  | SetPrepPreviewIntent
  | ClearPrepPreviewIntent
  | CollapseSessionIntent
  | ExpandSessionIntent
  | ExpandAllSessionsIntent
  | CollapseAllSessionsIntent
  | ExpandTodoIntent
  | CollapseTodoIntent
  | ExpandAllTodosIntent
  | CollapseAllTodosIntent
  | SetSelectionIntent
  | SetScrollOffsetIntent
  | SetSelectionMethodIntent
  | SessionActivityIntent
  | AgentActivityIntent
  | ClearTempHighlightIntent
  | SyncSessionsIntent
  | SyncTodosIntent
  | SetFilePaneIdIntent
  | ClearFilePaneIdIntent
  | SetAnimationModeIntent
  | SetConfigSubtabIntent
  | SetConfigGuidedModeIntent;

// ---------------------------------------------------------------------------
// Zustand store shape (state + actions)
// ---------------------------------------------------------------------------

export interface TuiStore extends TuiState {
  dispatch: (intent: Intent) => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const MAX_STICKY_PANES = 5;

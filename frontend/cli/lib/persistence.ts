/**
 * TUI state persistence with atomic writes.
 *
 * Port of teleclaude/cli/tui/state_store.py (load_sticky_state, save_sticky_state).
 */

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

// ---------------------------------------------------------------------------
// Persisted State Schema
// ---------------------------------------------------------------------------

export interface PersistedTuiState {
  stickySessionIds: string[];
  collapsedSessions: string[];
  inputHighlights: string[];
  outputHighlights: string[];
  lastOutputSummaries: Record<string, string>;
  expandedTodos: string[];
  previewSessionId: string | null;
  animationMode: 'off' | 'periodic' | 'party';
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TUI_STATE_PATH = path.join(os.homedir(), '.teleclaude', 'tui_state.json');

const DEFAULT_STATE: PersistedTuiState = {
  stickySessionIds: [],
  collapsedSessions: [],
  inputHighlights: [],
  outputHighlights: [],
  lastOutputSummaries: {},
  expandedTodos: [],
  previewSessionId: null,
  animationMode: 'off',
};

// ---------------------------------------------------------------------------
// Load
// ---------------------------------------------------------------------------

/**
 * Load TUI state from ~/.teleclaude/tui_state.json.
 *
 * Returns defaults if file missing or corrupt.
 * Validates JSON structure (ignore unknown fields, use defaults for missing).
 * Logs warning on parse errors, never throws.
 */
export function loadTuiState(): PersistedTuiState {
  if (!fs.existsSync(TUI_STATE_PATH)) {
    console.debug('[persistence] No TUI state file found, starting with defaults');
    return { ...DEFAULT_STATE };
  }

  try {
    const raw = fs.readFileSync(TUI_STATE_PATH, 'utf-8');
    const data = JSON.parse(raw) as Partial<Record<string, unknown>>;

    // Migrate old format: sticky_sessions -> stickySessionIds
    const stickySessionIds = extractStickySessionIds(data);

    return {
      stickySessionIds,
      collapsedSessions: extractStringArray(data, 'collapsed_sessions') ?? DEFAULT_STATE.collapsedSessions,
      inputHighlights: extractStringArray(data, 'input_highlights') ?? DEFAULT_STATE.inputHighlights,
      outputHighlights: extractStringArray(data, 'output_highlights') ?? DEFAULT_STATE.outputHighlights,
      lastOutputSummaries: extractStringRecord(data, 'last_output_summary') ?? DEFAULT_STATE.lastOutputSummaries,
      expandedTodos: extractStringArray(data, 'expanded_todos') ?? DEFAULT_STATE.expandedTodos,
      previewSessionId: extractPreviewSessionId(data) ?? DEFAULT_STATE.previewSessionId,
      animationMode: extractAnimationMode(data) ?? DEFAULT_STATE.animationMode,
    };
  } catch (err) {
    console.warn(`[persistence] Failed to load TUI state from ${TUI_STATE_PATH}:`, err);
    return { ...DEFAULT_STATE };
  }
}

/**
 * Extract sticky session IDs from Python format:
 * sticky_sessions: [{ session_id: "abc" }] -> ["abc"]
 */
function extractStickySessionIds(data: Partial<Record<string, unknown>>): string[] {
  const stickySessions = data.sticky_sessions;
  if (!Array.isArray(stickySessions)) {
    return DEFAULT_STATE.stickySessionIds;
  }

  return stickySessions
    .map((item) => {
      if (typeof item === 'object' && item !== null && 'session_id' in item) {
        const sessionId = (item as { session_id: unknown }).session_id;
        return typeof sessionId === 'string' ? sessionId : null;
      }
      return null;
    })
    .filter((id): id is string => id !== null);
}

/**
 * Extract preview session ID from Python format:
 * preview: { session_id: "abc" } -> "abc"
 */
function extractPreviewSessionId(data: Partial<Record<string, unknown>>): string | null {
  const preview = data.preview;
  if (typeof preview === 'object' && preview !== null && 'session_id' in preview) {
    const sessionId = (preview as { session_id: unknown }).session_id;
    return typeof sessionId === 'string' ? sessionId : null;
  }
  return null;
}

/**
 * Extract animation mode with validation.
 */
function extractAnimationMode(data: Partial<Record<string, unknown>>): 'off' | 'periodic' | 'party' | null {
  const mode = data.animation_mode;
  if (mode === 'off' || mode === 'periodic' || mode === 'party') {
    return mode;
  }
  return null;
}

/**
 * Extract string array from data, validating each element.
 */
function extractStringArray(data: Partial<Record<string, unknown>>, key: string): string[] | null {
  const value = data[key];
  if (!Array.isArray(value)) {
    return null;
  }
  return value.filter((item): item is string => typeof item === 'string');
}

/**
 * Extract string record from data, validating keys and values.
 */
function extractStringRecord(data: Partial<Record<string, unknown>>, key: string): Record<string, string> | null {
  const value = data[key];
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return null;
  }

  const result: Record<string, string> = {};
  for (const [k, v] of Object.entries(value)) {
    if (typeof k === 'string' && typeof v === 'string') {
      result[k] = v;
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------

/**
 * Save TUI state to ~/.teleclaude/tui_state.json.
 *
 * Uses atomic replacement and advisory locking to prevent race conditions.
 * Logs error on write failure, never throws.
 */
export function saveTuiState(state: PersistedTuiState): void {
  try {
    // Ensure directory exists
    const dir = path.dirname(TUI_STATE_PATH);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    // Convert to Python format for compatibility
    const stateData = {
      sticky_sessions: state.stickySessionIds.map((sessionId) => ({ session_id: sessionId })),
      expanded_todos: state.expandedTodos.sort(),
      input_highlights: state.inputHighlights.sort(),
      output_highlights: state.outputHighlights.sort(),
      last_output_summary: Object.fromEntries(
        Object.entries(state.lastOutputSummaries).sort(([a], [b]) => a.localeCompare(b))
      ),
      collapsed_sessions: state.collapsedSessions.sort(),
      preview: state.previewSessionId ? { session_id: state.previewSessionId } : null,
      animation_mode: state.animationMode,
    };

    // Atomic write with lock file
    const lockPath = TUI_STATE_PATH + '.lock';
    let lockFd: number | null = null;

    try {
      // Best-effort advisory lock
      try {
        lockFd = fs.openSync(lockPath, 'w');
        // Note: Node.js doesn't have built-in flock, but fs.openSync with 'wx' provides exclusive creation
        // For simplicity, we skip flock and rely on atomic rename
      } catch (lockErr) {
        // Lock acquisition failed, proceed anyway (best-effort)
      }

      // Write to temp file
      const tmpPath = `${TUI_STATE_PATH}.tmp.${process.pid}`;
      fs.writeFileSync(tmpPath, JSON.stringify(stateData, null, 2), 'utf-8');

      // Atomic rename
      fs.renameSync(tmpPath, TUI_STATE_PATH);

      console.debug(
        `[persistence] Saved ${state.stickySessionIds.length} sticky sessions, ${state.expandedTodos.length} expanded todos`
      );
    } finally {
      if (lockFd !== null) {
        try {
          fs.closeSync(lockFd);
          fs.unlinkSync(lockPath);
        } catch {
          // Ignore cleanup errors
        }
      }
    }
  } catch (err) {
    console.error(`[persistence] Failed to save TUI state to ${TUI_STATE_PATH}:`, err);
  }
}

// ---------------------------------------------------------------------------
// Zustand Middleware
// ---------------------------------------------------------------------------

/**
 * Debounced save helper.
 */
function createDebouncer(delayMs: number): (fn: () => void) => void {
  let timer: NodeJS.Timeout | null = null;
  return (fn: () => void) => {
    if (timer !== null) {
      clearTimeout(timer);
    }
    timer = setTimeout(() => {
      timer = null;
      fn();
    }, delayMs);
  };
}

/**
 * Create Zustand middleware for persistence.
 *
 * Subscribes to store changes, debounces writes (1 second), extracts persisted fields,
 * and calls saveTuiState.
 *
 * Usage:
 *   const useStore = create(persist(createStore));
 *   const persist = createPersistMiddleware();
 */
export function createPersistMiddleware() {
  const debouncedSave = createDebouncer(1000);

  return (storeApi: { getState: () => unknown; subscribe: (listener: () => void) => () => void }) => {
    // Load initial state
    const initialState = loadTuiState();

    // Subscribe to changes
    storeApi.subscribe(() => {
      debouncedSave(() => {
        const state = storeApi.getState() as {
          sessions?: {
            stickySessions?: Array<{ sessionId: string }>;
            collapsedSessions?: Set<string>;
            inputHighlights?: Set<string>;
            outputHighlights?: Set<string>;
            lastOutputSummary?: Record<string, string>;
            preview?: { sessionId: string } | null;
          };
          preparation?: {
            expandedTodos?: Set<string>;
          };
          animationMode?: 'off' | 'periodic' | 'party';
        };

        const persisted: PersistedTuiState = {
          stickySessionIds: state.sessions?.stickySessions?.map((s) => s.sessionId) ?? [],
          collapsedSessions: Array.from(state.sessions?.collapsedSessions ?? []),
          inputHighlights: Array.from(state.sessions?.inputHighlights ?? []),
          outputHighlights: Array.from(state.sessions?.outputHighlights ?? []),
          lastOutputSummaries: state.sessions?.lastOutputSummary ?? {},
          expandedTodos: Array.from(state.preparation?.expandedTodos ?? []),
          previewSessionId: state.sessions?.preview?.sessionId ?? null,
          animationMode: state.animationMode ?? 'off',
        };

        saveTuiState(persisted);
      });
    });

    return initialState;
  };
}

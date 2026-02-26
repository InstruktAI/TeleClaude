/**
 * Layout grid system for tmux pane arrangement.
 *
 * Supports 1-5 session panes alongside a TUI pane using a declarative grid
 * matrix. The TUI pane always occupies the left column; session panes fill
 * the right side in a 1x1, 1x2, 2x2, or 2x3 arrangement.
 *
 * Ported from: teleclaude/cli/tui/pane_manager.py (LAYOUT_SPECS, _render_layout)
 */

import {
  applyEvenHorizontalLayout,
  isTmuxAvailable,
  killPane,
  paneExists,
  splitWindow,
  tmuxExecArgsSafe,
} from "../tmux.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Describes the computed position and size for a single pane. */
export interface PaneRect {
  row: number;
  col: number;
  width: number;
  height: number;
}

/** Full layout description returned by `calculateLayout`. */
export interface LayoutGrid {
  tuiPane: { width: number; height: number };
  sessionPanes: PaneRect[];
  rows: number;
  cols: number;
}

/**
 * A cell in the layout matrix.
 *
 * - `"T"` = TUI pane
 * - Positive integer = 1-indexed session spec slot
 * - `null` = empty cell (TUI spans multiple rows)
 */
export type LayoutCell = "T" | number | null;

/** Declarative layout matrix (rows x cols). */
export interface LayoutSpec {
  rows: number;
  cols: number;
  grid: LayoutCell[][];
}

// ---------------------------------------------------------------------------
// Layout specifications (mirrors Python LAYOUT_SPECS)
// ---------------------------------------------------------------------------

/**
 * Predefined layout grids indexed by total pane count (TUI + sessions).
 *
 * Visual representations:
 *
 * 1 pane (TUI only):
 * ┌───────────────┐
 * │      TUI      │
 * └───────────────┘
 *
 * 2 panes (TUI + 1 session):
 * ┌───────┬───────┐
 * │  TUI  │  S1   │
 * └───────┴───────┘
 *
 * 3 panes (TUI + 2 sessions):
 * ┌───────┬───────┐
 * │  TUI  │  S1   │
 * │       ├───────┤
 * │       │  S2   │
 * └───────┴───────┘
 *
 * 4 panes (TUI + 3 sessions):
 * ┌───────┬───────┐
 * │  TUI  │  S1   │
 * ├───────┼───────┤
 * │  S3   │  S2   │
 * └───────┴───────┘
 *
 * 5 panes (TUI + 4 sessions):
 * ┌─────┬─────┬─────┐
 * │ TUI │ S1  │ S3  │
 * │     ├─────┼─────┤
 * │     │ S2  │ S4  │
 * └─────┴─────┴─────┘
 *
 * 6 panes (TUI + 5 sessions):
 * ┌─────┬─────┬─────┐
 * │ TUI │ S1  │ S3  │
 * ├─────┼─────┼─────┤
 * │ S5  │ S2  │ S4  │
 * └─────┴─────┴─────┘
 */
export const LAYOUT_SPECS: Record<number, LayoutSpec> = {
  1: { rows: 1, cols: 1, grid: [["T"]] },
  2: { rows: 1, cols: 2, grid: [["T", 1]] },
  3: { rows: 2, cols: 2, grid: [["T", 1], ["T", 2]] },
  4: { rows: 2, cols: 2, grid: [["T", 1], [3, 2]] },
  5: { rows: 2, cols: 3, grid: [["T", 1, 3], [null, 2, 4]] },
  6: { rows: 2, cols: 3, grid: [["T", 1, 3], [5, 2, 4]] },
};

/** Maximum number of session panes (excluding TUI). */
export const MAX_SESSION_PANES = 5;

// ---------------------------------------------------------------------------
// Layout calculation
// ---------------------------------------------------------------------------

/**
 * Calculate the layout grid for a given number of session panes.
 *
 * @param sessionCount - Number of session panes to display (1-5)
 * @param windowWidth  - Total terminal width in columns
 * @param windowHeight - Total terminal height in rows
 * @returns Layout grid with computed pane dimensions
 */
export function calculateLayout(
  sessionCount: number,
  windowWidth: number,
  windowHeight: number,
): LayoutGrid | null {
  const clamped = Math.min(Math.max(sessionCount, 0), MAX_SESSION_PANES);
  const totalPanes = 1 + clamped;
  const spec = LAYOUT_SPECS[totalPanes];
  if (!spec) return null;

  // TUI gets ~40% width, sessions get ~60%.
  // For 3-column layouts, TUI gets ~33%.
  const tuiWidthRatio = spec.cols <= 2 ? 0.4 : 0.33;
  const tuiWidth = Math.floor(windowWidth * tuiWidthRatio);
  const sessionTotalWidth = windowWidth - tuiWidth;
  const sessionCols = spec.cols - 1;
  const sessionColWidth =
    sessionCols > 0 ? Math.floor(sessionTotalWidth / sessionCols) : 0;

  const rowHeight =
    spec.rows > 0 ? Math.floor(windowHeight / spec.rows) : windowHeight;

  const sessionPanes: PaneRect[] = [];

  for (let row = 0; row < spec.rows; row++) {
    for (let col = 0; col < spec.cols; col++) {
      const cell = spec.grid[row]?.[col];
      if (typeof cell === "number") {
        sessionPanes.push({
          row,
          col: col - 1, // Normalize to 0-indexed session column
          width: sessionColWidth,
          height: rowHeight,
        });
      }
    }
  }

  return {
    tuiPane: { width: tuiWidth, height: windowHeight },
    sessionPanes,
    rows: spec.rows,
    cols: spec.cols,
  };
}

// ---------------------------------------------------------------------------
// Layout signature (change detection)
// ---------------------------------------------------------------------------

/**
 * Generate a signature string for the current layout configuration.
 *
 * The signature captures the structural shape of the layout (grid dimensions
 * and which session slots are sticky vs active) but intentionally excludes
 * the active session ID. This allows the active pane content to be swapped
 * via `respawn-pane` without tearing down the entire grid.
 *
 * @param stickyIds - Session IDs pinned to dedicated panes
 * @param previewId - Session ID in the active/preview slot (null if none)
 * @returns Opaque signature string for equality comparison
 */
export function getLayoutSignature(
  stickyIds: string[],
  previewId: string | null,
): string {
  // A preview that's already displayed as a sticky pane doesn't get its own
  // slot — rebuildLayout excludes it from specs. Normalise here so the
  // signature matches the pane count that will actually be rendered.
  const effectivePreviewId =
    previewId !== null && !stickyIds.includes(previewId) ? previewId : null;

  const slotCount = stickyIds.length + (effectivePreviewId !== null ? 1 : 0);
  const totalPanes = 1 + slotCount;
  const spec = LAYOUT_SPECS[totalPanes];
  if (!spec) return "";

  // Structural keys: sticky IDs are tracked by value, the active slot is
  // tracked by presence only (not by its session_id).
  const structuralKeys = [
    ...stickyIds,
    ...(effectivePreviewId !== null ? ["__active__"] : []),
  ];

  return JSON.stringify([spec.rows, spec.cols, spec.grid, structuralKeys]);
}

// ---------------------------------------------------------------------------
// Layout rendering (tmux pane creation)
// ---------------------------------------------------------------------------

/**
 * Parameters for rendering a session pane.
 */
export interface SessionPaneSpec {
  sessionId: string;
  command: string;
  isSticky: boolean;
}

/**
 * Result of a layout render: maps session IDs to created tmux pane IDs.
 */
export interface RenderResult {
  paneMap: Map<string, string>;
  tuiPaneId: string;
}

/**
 * Render the layout by creating tmux panes from a declarative spec.
 *
 * This destroys all existing session panes and recreates them from scratch.
 * The TUI pane (identified by `tuiPaneId`) is never killed.
 *
 * @param tuiPaneId     - The tmux pane ID running the TUI process
 * @param sessionSpecs  - Ordered list of session pane specifications
 * @param existingPanes - Pane IDs to clean up before rendering
 * @returns Map of session_id to newly created pane_id
 */
export function renderLayout(
  tuiPaneId: string,
  sessionSpecs: SessionPaneSpec[],
  existingPanes: string[] = [],
): RenderResult | null {
  if (!isTmuxAvailable()) return null;
  if (!tuiPaneId) return null;

  const specs = sessionSpecs.slice(0, MAX_SESSION_PANES);
  const totalPanes = 1 + specs.length;
  const layoutSpec = LAYOUT_SPECS[totalPanes];
  if (!layoutSpec) return null;

  // Clean up existing session panes.
  const seen = new Set<string>();
  for (const paneId of existingPanes) {
    if (!paneId || seen.has(paneId)) continue;
    seen.add(paneId);
    if (paneExists(paneId)) {
      killPane(paneId);
    }
  }

  const getSpec = (index: number): SessionPaneSpec | undefined =>
    index > 0 && index <= specs.length ? specs[index - 1] : undefined;

  // Track the top pane in each column for vertical splits.
  const colTopPanes: (string | null)[] = [tuiPaneId];
  for (let i = 1; i < layoutSpec.cols; i++) colTopPanes.push(null);

  const paneMap = new Map<string, string>();

  // Phase 1: Create top-row panes via horizontal splits.
  for (let col = 1; col < layoutSpec.cols; col++) {
    const cell = layoutSpec.grid[0]?.[col];
    if (typeof cell !== "number") continue;
    const spec = getSpec(cell);
    if (!spec) continue;

    let newPaneId: string | null;
    if (col === 1) {
      // First session column splits from the TUI pane.
      const percent =
        layoutSpec.cols === 2 && totalPanes <= 3 ? 60 : undefined;
      newPaneId = splitWindow(tuiPaneId, "h", { percent }, spec.command);
    } else {
      // Additional columns split from the previous column's top pane.
      const prevTop = colTopPanes[col - 1];
      if (!prevTop) continue;
      newPaneId = splitWindow(prevTop, "h", {}, spec.command);
    }

    if (newPaneId) {
      colTopPanes[col] = newPaneId;
      paneMap.set(spec.sessionId, newPaneId);
    }
  }

  // For 3-column layouts, equalize column widths.
  if (layoutSpec.cols === 3) {
    applyEvenHorizontalLayout();
  }

  // Phase 2: Create bottom-row panes via vertical splits.
  if (layoutSpec.rows > 1) {
    for (let col = 0; col < layoutSpec.cols; col++) {
      const cell = layoutSpec.grid[1]?.[col];
      if (typeof cell !== "number") continue;
      const spec = getSpec(cell);
      if (!spec) continue;

      const targetPane = colTopPanes[col];
      if (!targetPane) continue;

      const newPaneId = splitWindow(targetPane, "v", {}, spec.command);
      if (newPaneId) {
        paneMap.set(spec.sessionId, newPaneId);
      }
    }
  }

  return { paneMap, tuiPaneId };
}

/**
 * Apply a pre-calculated layout to existing panes by resizing them.
 *
 * This is a lightweight operation that adjusts pane dimensions without
 * destroying and recreating panes.
 *
 * @param grid    - The calculated layout grid
 * @param paneIds - Ordered list of pane IDs (TUI first, then sessions)
 */
export function applyLayout(grid: LayoutGrid, paneIds: string[]): void {
  if (!isTmuxAvailable()) return;
  if (paneIds.length === 0) return;

  // Resize TUI pane (first in list).
  const tuiId = paneIds[0];
  if (tuiId) {
    tmuxExecArgsSafe(
      "resize-pane",
      "-t",
      tuiId,
      "-x",
      String(grid.tuiPane.width),
      "-y",
      String(grid.tuiPane.height),
    );
  }

  // Resize session panes.
  for (let i = 0; i < grid.sessionPanes.length; i++) {
    const rect = grid.sessionPanes[i];
    const paneId = paneIds[i + 1]; // Offset by 1 (TUI is index 0)
    if (!rect || !paneId) continue;
    tmuxExecArgsSafe(
      "resize-pane",
      "-t",
      paneId,
      "-x",
      String(rect.width),
      "-y",
      String(rect.height),
    );
  }
}

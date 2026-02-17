/**
 * Double-press detection state machine for tree-like interaction gestures.
 *
 * Ported from teleclaude/cli/tui/views/interaction.py:TreeInteractionState
 */

export const DOUBLE_PRESS_THRESHOLD = 650; // milliseconds

export enum TreeInteractionAction {
  NONE = 'none',
  PREVIEW = 'preview',
  TOGGLE_STICKY = 'toggle_sticky',
  CLEAR_STICKY_PREVIEW = 'clear_sticky_preview',
}

export interface TreeInteractionDecision {
  action: TreeInteractionAction;
  now: number;
  clearPreview?: boolean;
}

/**
 * State machine for debouncing and detecting double-press gestures.
 *
 * State transitions:
 * - IDLE → (press) → track first press
 * - FIRST_PRESS → (same item within threshold) → TOGGLE_STICKY + guard period
 * - FIRST_PRESS → (same item after threshold) → PREVIEW + track new press
 * - FIRST_PRESS → (different item) → PREVIEW + track new press
 * - GUARD → (press same item within guard period) → NONE (suppress)
 * - GUARD → (press after guard period) → normal flow
 */
export class TreeInteractionState {
  private lastPressTime: number | null = null;
  private lastPressItemId: string | null = null;
  private doublePressGuardItemId: string | null = null;
  private doublePressGuardUntil: number | null = null;

  constructor(
    private readonly doublePressThreshold: number = DOUBLE_PRESS_THRESHOLD,
    private readonly now: () => number = () => Date.now()
  ) {}

  /**
   * Track a press event.
   */
  private markPress(itemId: string, timestamp: number): void {
    this.lastPressTime = timestamp;
    this.lastPressItemId = itemId;
  }

  /**
   * Start guard period after a toggle to prevent triple-press accidents.
   */
  private markDoublePressGuard(itemId: string, timestamp: number): void {
    this.doublePressGuardItemId = itemId;
    this.doublePressGuardUntil = timestamp + this.doublePressThreshold;
  }

  /**
   * Check if an item is currently in the guard period.
   */
  private isDoublePressGuarded(itemId: string, timestamp: number): boolean {
    if (this.doublePressGuardItemId !== itemId) {
      return false;
    }

    const guardUntil = this.doublePressGuardUntil;
    if (guardUntil === null) {
      return false;
    }

    if (timestamp >= guardUntil) {
      // Guard expired, clear it
      this.doublePressGuardItemId = null;
      this.doublePressGuardUntil = null;
      return false;
    }

    return true;
  }

  /**
   * Decide what action to take for a press event.
   *
   * @param itemId - The item being pressed
   * @param isSticky - Whether the item is currently in sticky preview mode
   * @param allowStickyToggle - Whether double-press toggle is enabled
   * @returns The action to perform
   */
  decidePreviewAction(
    itemId: string,
    isSticky: boolean = false,
    allowStickyToggle: boolean = true
  ): TreeInteractionDecision {
    const timestamp = this.now();

    // Guard period: suppress immediate re-press after toggle
    if (allowStickyToggle && this.isDoublePressGuarded(itemId, timestamp)) {
      return {
        action: TreeInteractionAction.NONE,
        now: timestamp,
      };
    }

    // Double press detection: same item within threshold
    if (
      allowStickyToggle &&
      this.lastPressItemId === itemId &&
      this.lastPressTime !== null &&
      timestamp - this.lastPressTime < this.doublePressThreshold
    ) {
      // This is a double press → toggle sticky mode
      this.markDoublePressGuard(itemId, timestamp);
      this.lastPressItemId = null;
      this.lastPressTime = null;

      return {
        action: TreeInteractionAction.TOGGLE_STICKY,
        now: timestamp,
        clearPreview: isSticky,
      };
    }

    // Single press (or first press of a potential double)
    this.markPress(itemId, timestamp);

    if (isSticky) {
      // Item is already sticky → clear it
      return {
        action: TreeInteractionAction.CLEAR_STICKY_PREVIEW,
        now: timestamp,
      };
    }

    // Normal preview
    return {
      action: TreeInteractionAction.PREVIEW,
      now: timestamp,
    };
  }

  /**
   * Reset all state.
   */
  reset(): void {
    this.lastPressTime = null;
    this.lastPressItemId = null;
    this.doublePressGuardItemId = null;
    this.doublePressGuardUntil = null;
  }
}

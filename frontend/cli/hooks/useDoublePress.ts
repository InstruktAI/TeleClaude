/**
 * Double-press gesture hook for Ink components.
 *
 * Wraps the `TreeInteractionState` state machine from `@/lib/interaction/gesture.ts`
 * and exposes a single `handlePress` callback. Components call `handlePress(itemId)`
 * on each selection event; this hook determines whether it is a single press
 * (preview) or a double press (toggle sticky) and invokes the appropriate callback.
 */

import { useRef, useCallback } from "react";

import {
  TreeInteractionState,
  TreeInteractionAction,
} from "@/lib/interaction/gesture.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UseDoublePressResult {
  /** Call this on every press/select event with the item identifier. */
  handlePress: (itemId: string) => void;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * @param onPreview - Called on a single press (first press or expired double-press window).
 * @param onToggle  - Called on a confirmed double press within the threshold.
 */
export function useDoublePress(
  onPreview: (id: string) => void,
  onToggle: (id: string) => void,
): UseDoublePressResult {
  // Persistent state machine instance across renders.
  const stateRef = useRef<TreeInteractionState>(new TreeInteractionState());

  const handlePress = useCallback(
    (itemId: string) => {
      const decision = stateRef.current.decidePreviewAction(itemId);

      switch (decision.action) {
        case TreeInteractionAction.PREVIEW:
          onPreview(itemId);
          break;

        case TreeInteractionAction.TOGGLE_STICKY:
          onToggle(itemId);
          break;

        case TreeInteractionAction.CLEAR_STICKY_PREVIEW:
          // Item is already sticky; treat as a preview toggle-off.
          onPreview(itemId);
          break;

        case TreeInteractionAction.NONE:
          // Guard period active; suppress the press.
          break;
      }
    },
    [onPreview, onToggle],
  );

  return { handlePress };
}

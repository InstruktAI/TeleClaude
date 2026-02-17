/**
 * Scroll offset management for list views.
 *
 * Tracks a selected index within a scrollable viewport, keeping the
 * selection visible by adjusting the scroll offset when the selection
 * moves beyond the viewport edges. Provides imperative navigation
 * methods for single-step and page-based movement.
 */

import { useState, useCallback, useMemo } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UseScrollableResult {
  /** Current scroll offset (index of the first visible item). */
  scrollOffset: number;
  /** Currently selected item index. */
  selectedIndex: number;
  /** Jump to an exact index, adjusting scroll if needed. */
  scrollTo: (index: number) => void;
  /** Move selection up by one. */
  scrollUp: () => void;
  /** Move selection down by one. */
  scrollDown: () => void;
  /** Move selection up by one page (viewport height). */
  pageUp: () => void;
  /** Move selection down by one page (viewport height). */
  pageDown: () => void;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * @param totalItems     - Total number of items in the list.
 * @param viewportHeight - Number of items visible at once.
 */
export function useScrollable(
  totalItems: number,
  viewportHeight: number,
): UseScrollableResult {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [scrollOffset, setScrollOffset] = useState(0);

  /**
   * Clamp a value to [min, max].
   */
  const clamp = useCallback(
    (value: number, min: number, max: number): number =>
      Math.max(min, Math.min(max, value)),
    [],
  );

  /**
   * Given a new selected index, compute the scroll offset that keeps the
   * selection within the viewport.
   */
  const adjustScroll = useCallback(
    (newIndex: number, currentOffset: number): number => {
      if (totalItems <= viewportHeight) return 0;

      let offset = currentOffset;

      // Selection moved above the viewport.
      if (newIndex < offset) {
        offset = newIndex;
      }

      // Selection moved below the viewport.
      if (newIndex >= offset + viewportHeight) {
        offset = newIndex - viewportHeight + 1;
      }

      const maxOffset = Math.max(0, totalItems - viewportHeight);
      return clamp(offset, 0, maxOffset);
    },
    [totalItems, viewportHeight, clamp],
  );

  const scrollTo = useCallback(
    (index: number) => {
      const maxIndex = Math.max(0, totalItems - 1);
      const clamped = clamp(index, 0, maxIndex);
      setSelectedIndex(clamped);
      setScrollOffset((prev) => adjustScroll(clamped, prev));
    },
    [totalItems, clamp, adjustScroll],
  );

  const scrollUp = useCallback(() => {
    setSelectedIndex((prev) => {
      const next = Math.max(0, prev - 1);
      setScrollOffset((off) => adjustScroll(next, off));
      return next;
    });
  }, [adjustScroll]);

  const scrollDown = useCallback(() => {
    setSelectedIndex((prev) => {
      const maxIndex = Math.max(0, totalItems - 1);
      const next = Math.min(maxIndex, prev + 1);
      setScrollOffset((off) => adjustScroll(next, off));
      return next;
    });
  }, [totalItems, adjustScroll]);

  const pageUp = useCallback(() => {
    setSelectedIndex((prev) => {
      const next = Math.max(0, prev - viewportHeight);
      setScrollOffset((off) => adjustScroll(next, off));
      return next;
    });
  }, [viewportHeight, adjustScroll]);

  const pageDown = useCallback(() => {
    setSelectedIndex((prev) => {
      const maxIndex = Math.max(0, totalItems - 1);
      const next = Math.min(maxIndex, prev + viewportHeight);
      setScrollOffset((off) => adjustScroll(next, off));
      return next;
    });
  }, [totalItems, viewportHeight, adjustScroll]);

  return useMemo(
    () => ({
      scrollOffset,
      selectedIndex,
      scrollTo,
      scrollUp,
      scrollDown,
      pageUp,
      pageDown,
    }),
    [scrollOffset, selectedIndex, scrollTo, scrollUp, scrollDown, pageUp, pageDown],
  );
}

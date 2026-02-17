import { describe, it, expect } from 'vitest'
import {
  TreeInteractionState,
  TreeInteractionAction,
  DOUBLE_PRESS_THRESHOLD,
} from '@/lib/interaction/gesture'

// ---------------------------------------------------------------------------
// Helper: create state machine with injectable clock
// ---------------------------------------------------------------------------

function createGesture(startTime: number = 0) {
  let time = startTime
  const state = new TreeInteractionState(DOUBLE_PRESS_THRESHOLD, () => time)
  return {
    state,
    setTime(t: number) {
      time = t
    },
    advance(ms: number) {
      time += ms
    },
  }
}

// ---------------------------------------------------------------------------
// Single press
// ---------------------------------------------------------------------------

describe('TreeInteractionState', () => {
  describe('single press', () => {
    it('should return PREVIEW on first press', () => {
      const { state } = createGesture()
      const result = state.decidePreviewAction('item-1')
      expect(result.action).toBe(TreeInteractionAction.PREVIEW)
    })

    it('should return PREVIEW for non-sticky item', () => {
      const { state } = createGesture()
      const result = state.decidePreviewAction('item-1', false)
      expect(result.action).toBe(TreeInteractionAction.PREVIEW)
    })

    it('should return CLEAR_STICKY_PREVIEW for sticky item', () => {
      const { state } = createGesture()
      const result = state.decidePreviewAction('item-1', true)
      expect(result.action).toBe(TreeInteractionAction.CLEAR_STICKY_PREVIEW)
    })

    it('should include timestamp in decision', () => {
      const { state, setTime } = createGesture()
      setTime(12345)
      const result = state.decidePreviewAction('item-1')
      expect(result.now).toBe(12345)
    })
  })

  // ---------------------------------------------------------------------------
  // Double press
  // ---------------------------------------------------------------------------

  describe('double press', () => {
    it('should return TOGGLE_STICKY on second press within threshold', () => {
      const { state, advance } = createGesture()
      state.decidePreviewAction('item-1')
      advance(300) // within 650ms
      const result = state.decidePreviewAction('item-1')
      expect(result.action).toBe(TreeInteractionAction.TOGGLE_STICKY)
    })

    it('should return TOGGLE_STICKY at exactly threshold - 1ms', () => {
      const { state, advance } = createGesture()
      state.decidePreviewAction('item-1')
      advance(DOUBLE_PRESS_THRESHOLD - 1)
      const result = state.decidePreviewAction('item-1')
      expect(result.action).toBe(TreeInteractionAction.TOGGLE_STICKY)
    })

    it('should return PREVIEW after threshold expires', () => {
      const { state, advance } = createGesture()
      state.decidePreviewAction('item-1')
      advance(DOUBLE_PRESS_THRESHOLD) // exactly at threshold
      const result = state.decidePreviewAction('item-1')
      expect(result.action).toBe(TreeInteractionAction.PREVIEW)
    })

    it('should set clearPreview when double-pressing a sticky item', () => {
      const { state, advance } = createGesture()
      state.decidePreviewAction('item-1', true)
      advance(200)
      const result = state.decidePreviewAction('item-1', true)
      expect(result.action).toBe(TreeInteractionAction.TOGGLE_STICKY)
      expect(result.clearPreview).toBe(true)
    })

    it('should not set clearPreview when double-pressing a non-sticky item', () => {
      const { state, advance } = createGesture()
      state.decidePreviewAction('item-1', false)
      advance(200)
      const result = state.decidePreviewAction('item-1', false)
      expect(result.action).toBe(TreeInteractionAction.TOGGLE_STICKY)
      expect(result.clearPreview).toBe(false)
    })
  })

  // ---------------------------------------------------------------------------
  // Different item resets
  // ---------------------------------------------------------------------------

  describe('different item resets', () => {
    it('should return PREVIEW when pressing a different item', () => {
      const { state, advance } = createGesture()
      state.decidePreviewAction('item-1')
      advance(100)
      const result = state.decidePreviewAction('item-2')
      expect(result.action).toBe(TreeInteractionAction.PREVIEW)
    })

    it('should track the new item for subsequent double press', () => {
      const { state, advance } = createGesture()
      state.decidePreviewAction('item-1')
      advance(100)
      state.decidePreviewAction('item-2') // switch to item-2
      advance(100)
      const result = state.decidePreviewAction('item-2') // double press on item-2
      expect(result.action).toBe(TreeInteractionAction.TOGGLE_STICKY)
    })
  })

  // ---------------------------------------------------------------------------
  // Guard period
  // ---------------------------------------------------------------------------

  describe('guard period', () => {
    it('should suppress press during guard period after toggle', () => {
      const { state, advance } = createGesture()
      state.decidePreviewAction('item-1')
      advance(200)
      state.decidePreviewAction('item-1') // toggle (starts guard)
      advance(100) // within guard (guard = threshold = 650ms)
      const result = state.decidePreviewAction('item-1')
      expect(result.action).toBe(TreeInteractionAction.NONE)
    })

    it('should allow press after guard period expires', () => {
      const { state, advance } = createGesture()
      state.decidePreviewAction('item-1')
      advance(200)
      state.decidePreviewAction('item-1') // toggle
      advance(DOUBLE_PRESS_THRESHOLD) // guard expired
      const result = state.decidePreviewAction('item-1')
      expect(result.action).toBe(TreeInteractionAction.PREVIEW)
    })

    it('should not guard a different item', () => {
      const { state, advance } = createGesture()
      state.decidePreviewAction('item-1')
      advance(200)
      state.decidePreviewAction('item-1') // toggle on item-1
      advance(100) // within guard for item-1
      const result = state.decidePreviewAction('item-2') // different item
      expect(result.action).toBe(TreeInteractionAction.PREVIEW)
    })
  })

  // ---------------------------------------------------------------------------
  // allowStickyToggle = false
  // ---------------------------------------------------------------------------

  describe('allowStickyToggle disabled', () => {
    it('should always return PREVIEW regardless of timing', () => {
      const { state, advance } = createGesture()
      state.decidePreviewAction('item-1', false, true)
      advance(100)
      // With toggle disabled, second quick press should be PREVIEW not TOGGLE
      const result = state.decidePreviewAction('item-1', false, false)
      expect(result.action).toBe(TreeInteractionAction.PREVIEW)
    })

    it('should skip guard check when toggle disabled', () => {
      const { state, advance } = createGesture()
      state.decidePreviewAction('item-1')
      advance(200)
      state.decidePreviewAction('item-1') // toggle (starts guard)
      advance(100) // within guard
      // With toggle disabled, guard is skipped
      const result = state.decidePreviewAction('item-1', false, false)
      expect(result.action).toBe(TreeInteractionAction.PREVIEW)
    })
  })

  // ---------------------------------------------------------------------------
  // Reset
  // ---------------------------------------------------------------------------

  describe('reset', () => {
    it('should clear all internal state', () => {
      const { state, advance } = createGesture()
      state.decidePreviewAction('item-1')
      advance(100)
      state.reset()
      advance(100) // would have been within threshold
      const result = state.decidePreviewAction('item-1')
      // After reset, first press is always PREVIEW
      expect(result.action).toBe(TreeInteractionAction.PREVIEW)
    })

    it('should clear guard period', () => {
      const { state, advance } = createGesture()
      state.decidePreviewAction('item-1')
      advance(200)
      state.decidePreviewAction('item-1') // toggle, starts guard
      state.reset()
      advance(50) // would be guarded without reset
      const result = state.decidePreviewAction('item-1')
      expect(result.action).toBe(TreeInteractionAction.PREVIEW)
    })
  })

  // ---------------------------------------------------------------------------
  // Custom threshold
  // ---------------------------------------------------------------------------

  describe('custom threshold', () => {
    it('should respect custom double press threshold', () => {
      let time = 0
      const state = new TreeInteractionState(100, () => time) // 100ms threshold
      state.decidePreviewAction('item-1')
      time = 50 // within 100ms
      const result = state.decidePreviewAction('item-1')
      expect(result.action).toBe(TreeInteractionAction.TOGGLE_STICKY)
    })

    it('should expire with custom threshold', () => {
      let time = 0
      const state = new TreeInteractionState(100, () => time)
      state.decidePreviewAction('item-1')
      time = 100 // exactly at threshold
      const result = state.decidePreviewAction('item-1')
      expect(result.action).toBe(TreeInteractionAction.PREVIEW)
    })
  })

  // ---------------------------------------------------------------------------
  // Edge cases
  // ---------------------------------------------------------------------------

  describe('edge cases', () => {
    it('should handle rapid triple press (press, toggle, guard)', () => {
      const { state, advance } = createGesture()
      const r1 = state.decidePreviewAction('item-1')
      expect(r1.action).toBe(TreeInteractionAction.PREVIEW)

      advance(100)
      const r2 = state.decidePreviewAction('item-1')
      expect(r2.action).toBe(TreeInteractionAction.TOGGLE_STICKY)

      advance(50)
      const r3 = state.decidePreviewAction('item-1')
      expect(r3.action).toBe(TreeInteractionAction.NONE) // guarded
    })

    it('should handle alternating items', () => {
      const { state, advance } = createGesture()
      state.decidePreviewAction('a')
      advance(100)
      state.decidePreviewAction('b')
      advance(100)
      state.decidePreviewAction('a')
      advance(100)
      // Last two presses are on 'a', within threshold -> toggle
      const result = state.decidePreviewAction('a')
      expect(result.action).toBe(TreeInteractionAction.TOGGLE_STICKY)
    })
  })
})

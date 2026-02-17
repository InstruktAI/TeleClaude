/**
 * Double-buffered animation engine with priority queue.
 *
 * Manages multiple named render targets, each with its own animation slot,
 * back/front color buffers, and a bounded queue for pending animations.
 * Higher-priority animations interrupt lower-priority ones on the same target.
 *
 * The engine ticks via setInterval (injectable for testing). Each tick calls
 * update() which: evaluates each slot, calls the algorithm for the current
 * frame, writes to the back buffer, then swaps buffers atomically.
 *
 * No React, no DOM -- pure TypeScript.
 */

import type {
  AnimationAlgorithm,
  AnimationConfig,
  AnimationSlot,
  AnimationTarget,
  ColorGrid,
} from './types'
import { AnimationPriority } from './types'

// ---------------------------------------------------------------------------
// Internal slot state
// ---------------------------------------------------------------------------

interface SlotState {
  slot: AnimationSlot | null
  localFrame: number
  queue: QueueEntry[]
  looping: boolean
}

interface QueueEntry {
  algorithm: AnimationAlgorithm
  config: AnimationConfig
  priority: AnimationPriority
  duration: number | null
  targetId: string
}

// ---------------------------------------------------------------------------
// Engine
// ---------------------------------------------------------------------------

const MAX_QUEUE_SIZE = 5
const DEFAULT_FPS = 10

export class AnimationEngine {
  // Per-target state
  private _slots: Map<string, SlotState> = new Map()
  private _targets: Map<string, AnimationTarget> = new Map()

  // Double buffers: target id -> ColorGrid
  private _front: Map<string, ColorGrid> = new Map()
  private _back: Map<string, ColorGrid> = new Map()

  // Timing
  private _fps: number = DEFAULT_FPS
  private _timerId: ReturnType<typeof setInterval> | null = null
  private _globalFrame: number = 0
  private _enabled: boolean = true

  // Injectable timer for testing
  private _setInterval: typeof setInterval
  private _clearInterval: typeof clearInterval

  constructor(opts?: {
    setInterval?: typeof setInterval
    clearInterval?: typeof clearInterval
  }) {
    this._setInterval = opts?.setInterval ?? globalThis.setInterval
    this._clearInterval = opts?.clearInterval ?? globalThis.clearInterval
  }

  // -----------------------------------------------------------------------
  // Target registration
  // -----------------------------------------------------------------------

  /**
   * Register (or replace) a named render target.
   *
   * Must be called before playing animations on the target.
   */
  registerTarget(id: string, target: AnimationTarget): void {
    this._targets.set(id, target)
    this._ensureSlot(id)
  }

  // -----------------------------------------------------------------------
  // Playback
  // -----------------------------------------------------------------------

  /**
   * Start a new animation on the given target.
   *
   * Priority rules (same as the Python engine):
   *   - Higher priority interrupts the current animation.
   *   - Same priority replaces the current animation.
   *   - Lower priority is queued (up to MAX_QUEUE_SIZE).
   */
  play(slot: AnimationSlot): void {
    if (!this._enabled) return

    const state = this._ensureSlot(slot.targetId)

    if (state.slot === null || slot.priority >= state.slot.priority) {
      // Interrupt / replace
      state.slot = slot
      state.localFrame = 0
      state.looping = false
    } else {
      // Queue (bounded)
      if (state.queue.length < MAX_QUEUE_SIZE) {
        state.queue.push({
          algorithm: slot.algorithm,
          config: slot.config,
          priority: slot.priority,
          duration: slot.duration,
          targetId: slot.targetId,
        })
      }
    }
  }

  /**
   * Stop all animations for a specific target and clear its buffers.
   */
  stopTarget(targetId: string): void {
    const state = this._slots.get(targetId)
    if (state) {
      state.slot = null
      state.localFrame = 0
      state.queue.length = 0
      state.looping = false
    }
    this._front.get(targetId)?.clear()
    this._back.get(targetId)?.clear()
  }

  /**
   * Stop ALL animations across every target and clear all buffers.
   */
  stopAll(): void {
    for (const id of this._slots.keys()) {
      this.stopTarget(id)
    }
  }

  /**
   * Set the current animation on a target to loop.
   */
  setLooping(targetId: string, looping: boolean): void {
    const state = this._slots.get(targetId)
    if (state) state.looping = looping
  }

  // -----------------------------------------------------------------------
  // Frame update
  // -----------------------------------------------------------------------

  /**
   * Advance all slots by one frame and swap buffers.
   *
   * Called automatically by the internal timer, but can also be called
   * manually for testing or external timing control.
   */
  update(): void {
    this._globalFrame++

    for (const [targetId, state] of this._slots) {
      const backBuffer = this._ensureBuffer(this._back, targetId)

      if (state.slot) {
        const target = this._targets.get(targetId)
        if (!target) {
          backBuffer.clear()
          continue
        }

        // Compute frame
        const grid = state.slot.algorithm(
          state.localFrame,
          state.slot.config,
          target,
        )

        // Merge into back buffer (algorithms return full grids per frame)
        backBuffer.clear()
        for (const [key, value] of grid) {
          backBuffer.set(key, value)
        }

        state.localFrame++

        // Check completion
        if (
          state.slot.duration !== null &&
          state.localFrame >= state.slot.duration
        ) {
          if (state.looping) {
            state.localFrame = 0
          } else if (state.queue.length > 0) {
            const next = state.queue.shift()!
            state.slot = {
              algorithm: next.algorithm,
              config: next.config,
              priority: next.priority,
              startFrame: this._globalFrame,
              duration: next.duration,
              targetId: next.targetId,
            }
            state.localFrame = 0
            state.looping = false
          } else {
            state.slot = null
            backBuffer.clear()
          }
        }
      } else {
        backBuffer.clear()
      }
    }

    // Atomic buffer swap
    const tmp = this._front
    this._front = this._back
    this._back = tmp
  }

  // -----------------------------------------------------------------------
  // Color queries
  // -----------------------------------------------------------------------

  /**
   * Get the current frame's color grid for a target.
   *
   * Reads from the front buffer (stable snapshot during rendering).
   * Returns an empty Map when the target has no active animation.
   */
  getColors(targetId: string): ColorGrid {
    return this._front.get(targetId) ?? new Map()
  }

  /**
   * Get the palette index for a single pixel on a target.
   *
   * Returns undefined when no animation color is set, or when the
   * palette index is -1 (clear).
   */
  getPixelColor(targetId: string, x: number, y: number): number | undefined {
    const grid = this._front.get(targetId)
    if (!grid) return undefined
    const key = `${x},${y}`
    const value = grid.get(key)
    if (value === undefined || value === -1) return undefined
    return value
  }

  /**
   * Get the current animation palette for a target.
   *
   * Returns an empty array when no animation is active on the target.
   */
  getCurrentPalette(targetId: string): string[] {
    const state = this._slots.get(targetId)
    if (!state?.slot) return []
    return state.slot.config.palette
  }

  // -----------------------------------------------------------------------
  // Engine lifecycle
  // -----------------------------------------------------------------------

  /** Set the frame rate (frames per second). Default 10. */
  setFPS(fps: number): void {
    this._fps = Math.max(1, fps)
    // Restart timer if running
    if (this._timerId !== null) {
      this.stop()
      this.start()
    }
  }

  /** Current FPS. */
  get fps(): number {
    return this._fps
  }

  /** Whether the engine is ticking. */
  get isRunning(): boolean {
    return this._timerId !== null
  }

  /** Whether animations are enabled. */
  get isEnabled(): boolean {
    return this._enabled
  }

  set isEnabled(value: boolean) {
    this._enabled = value
    if (!value) this.stopAll()
  }

  /** Global frame counter (monotonically increasing). */
  get frame(): number {
    return this._globalFrame
  }

  /** Start the engine timer. */
  start(): void {
    if (this._timerId !== null) return
    const interval = Math.round(1000 / this._fps)
    this._timerId = this._setInterval(() => this.update(), interval)
  }

  /** Stop the engine timer. Buffers and slots are preserved. */
  stop(): void {
    if (this._timerId !== null) {
      this._clearInterval(this._timerId)
      this._timerId = null
    }
  }

  /** Full teardown: stop timer, clear all state. */
  destroy(): void {
    this.stop()
    this._slots.clear()
    this._targets.clear()
    this._front.clear()
    this._back.clear()
    this._globalFrame = 0
  }

  // -----------------------------------------------------------------------
  // Internal
  // -----------------------------------------------------------------------

  private _ensureSlot(targetId: string): SlotState {
    let state = this._slots.get(targetId)
    if (!state) {
      state = {
        slot: null,
        localFrame: 0,
        queue: [],
        looping: false,
      }
      this._slots.set(targetId, state)
      this._front.set(targetId, new Map())
      this._back.set(targetId, new Map())
    }
    return state
  }

  private _ensureBuffer(
    buffers: Map<string, ColorGrid>,
    targetId: string,
  ): ColorGrid {
    let buf = buffers.get(targetId)
    if (!buf) {
      buf = new Map()
      buffers.set(targetId, buf)
    }
    return buf
  }
}

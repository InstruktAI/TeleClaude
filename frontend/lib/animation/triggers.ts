/**
 * Animation triggers.
 *
 * Triggers decide *when* animations fire. They observe external signals
 * (timers, agent events, state changes) and invoke a callback that
 * typically calls engine.play().
 *
 * No React, no DOM -- pure TypeScript with injectable timers.
 */

import type { AnimationEngine } from './engine'

// ---------------------------------------------------------------------------
// Callback type
// ---------------------------------------------------------------------------

/**
 * Callback invoked when a trigger fires.
 *
 * Receives the engine instance so it can call engine.play() directly.
 */
export type TriggerCallback = (engine: AnimationEngine) => void

// ---------------------------------------------------------------------------
// PeriodicTrigger
// ---------------------------------------------------------------------------

/**
 * Fires an animation at a fixed interval (default 60 seconds).
 *
 * Use for ambient/idle animations that run on a timer regardless of activity.
 */
export class PeriodicTrigger {
  private _interval: number
  private _timerId: ReturnType<typeof setInterval> | null = null
  private _engine: AnimationEngine | null = null
  private _callback: TriggerCallback | null = null

  // Injectable for testing
  private _setInterval: typeof setInterval
  private _clearInterval: typeof clearInterval

  constructor(
    intervalSeconds: number = 60,
    opts?: {
      setInterval?: typeof setInterval
      clearInterval?: typeof clearInterval
    },
  ) {
    this._interval = intervalSeconds * 1000
    this._setInterval = opts?.setInterval ?? globalThis.setInterval
    this._clearInterval = opts?.clearInterval ?? globalThis.clearInterval
  }

  /** Start the periodic timer. */
  start(engine: AnimationEngine, callback: TriggerCallback): void {
    this.stop()
    this._engine = engine
    this._callback = callback
    this._timerId = this._setInterval(() => {
      if (this._engine && this._callback) {
        this._callback(this._engine)
      }
    }, this._interval)
  }

  /** Stop the periodic timer. */
  stop(): void {
    if (this._timerId !== null) {
      this._clearInterval(this._timerId)
      this._timerId = null
    }
    this._engine = null
    this._callback = null
  }

  /** Whether the trigger is active. */
  isActive(): boolean {
    return this._timerId !== null
  }

  /** Current interval in seconds. */
  get intervalSeconds(): number {
    return this._interval / 1000
  }

  /** Update the interval (restarts the timer if running). */
  setInterval(seconds: number): void {
    this._interval = seconds * 1000
    if (this._timerId !== null && this._engine && this._callback) {
      const engine = this._engine
      const callback = this._callback
      this.stop()
      this.start(engine, callback)
    }
  }
}

// ---------------------------------------------------------------------------
// ActivityTrigger
// ---------------------------------------------------------------------------

/** Agent activity event types that can fire animations. */
export type ActivityEvent =
  | 'tool_use'
  | 'streaming'
  | 'thinking'
  | 'message'
  | 'error'
  | 'connected'
  | 'disconnected'

/**
 * Fires an animation in response to agent activity events.
 *
 * Debounced: rapid events within the cooldown window are coalesced into
 * a single animation trigger. Different event types can map to different
 * callbacks.
 */
export class ActivityTrigger {
  private _engine: AnimationEngine | null = null
  private _defaultCallback: TriggerCallback | null = null
  private _eventCallbacks: Map<ActivityEvent, TriggerCallback> = new Map()
  private _cooldownMs: number
  private _lastFireTime: number = 0
  private _active: boolean = false

  constructor(cooldownMs: number = 500) {
    this._cooldownMs = cooldownMs
  }

  /** Start the trigger. Subsequent emit() calls will invoke the callback. */
  start(engine: AnimationEngine, callback: TriggerCallback): void {
    this._engine = engine
    this._defaultCallback = callback
    this._active = true
  }

  /** Stop the trigger. emit() calls become no-ops. */
  stop(): void {
    this._engine = null
    this._defaultCallback = null
    this._eventCallbacks.clear()
    this._active = false
  }

  /** Whether the trigger is active. */
  isActive(): boolean {
    return this._active
  }

  /**
   * Register a callback for a specific event type.
   *
   * Falls back to the default callback when no event-specific one is registered.
   */
  on(event: ActivityEvent, callback: TriggerCallback): void {
    this._eventCallbacks.set(event, callback)
  }

  /**
   * Emit an activity event.
   *
   * Respects the cooldown window: if called within cooldownMs of the last
   * fire, the event is silently dropped.
   */
  emit(event: ActivityEvent): void {
    if (!this._active || !this._engine) return

    const now = Date.now()
    if (now - this._lastFireTime < this._cooldownMs) return
    this._lastFireTime = now

    const callback = this._eventCallbacks.get(event) ?? this._defaultCallback
    if (callback) {
      callback(this._engine)
    }
  }
}

// ---------------------------------------------------------------------------
// StateDrivenTrigger
// ---------------------------------------------------------------------------

/**
 * Fires an animation when a named state value changes.
 *
 * Tracks key-value pairs; when a key's value changes, the registered
 * callback fires. Useful for connection status, agent mode, etc.
 */
export class StateDrivenTrigger {
  private _engine: AnimationEngine | null = null
  private _callback: TriggerCallback | null = null
  private _state: Map<string, string> = new Map()
  private _active: boolean = false

  /** Start the trigger. */
  start(engine: AnimationEngine, callback: TriggerCallback): void {
    this._engine = engine
    this._callback = callback
    this._active = true
  }

  /** Stop the trigger and clear tracked state. */
  stop(): void {
    this._engine = null
    this._callback = null
    this._state.clear()
    this._active = false
  }

  /** Whether the trigger is active. */
  isActive(): boolean {
    return this._active
  }

  /**
   * Set a state value.
   *
   * If the value differs from the previously stored value for this key,
   * the callback fires. First-time sets also fire.
   */
  setState(key: string, value: string): void {
    const previous = this._state.get(key)
    if (previous === value) return

    this._state.set(key, value)

    if (this._active && this._engine && this._callback) {
      this._callback(this._engine)
    }
  }

  /** Get the current value of a tracked state key. */
  getState(key: string): string | undefined {
    return this._state.get(key)
  }

  /** Clear a specific state key (next set will fire). */
  clearState(key: string): void {
    this._state.delete(key)
  }
}

/**
 * Core type definitions for the animation engine.
 *
 * Renderer-agnostic: shared between terminal (braille+chalk) and web (canvas).
 * No side effects on import.
 */

import type { AgentType } from '@/lib/theme/tokens'

// ---------------------------------------------------------------------------
// Color grid
// ---------------------------------------------------------------------------

/**
 * Maps pixel coordinates to palette indices.
 *
 * Key format: "x,y" (stringified for Map ergonomics).
 * Value: palette index, or -1 to clear the pixel.
 */
export type ColorGrid = Map<string, number>

/** Convenience helpers for ColorGrid coordinate keys. */
export function colorKey(x: number, y: number): string {
  return `${x},${y}`
}

export function parseColorKey(key: string): [number, number] {
  const i = key.indexOf(',')
  return [Number(key.slice(0, i)), Number(key.slice(i + 1))]
}

// ---------------------------------------------------------------------------
// Animation algorithm
// ---------------------------------------------------------------------------

/**
 * Pure function that computes one frame of an animation.
 *
 * Receives the current frame counter, configuration, and target geometry.
 * Returns a ColorGrid mapping pixels to palette indices. Must have no side
 * effects -- all randomness should be seeded from `frame`.
 */
export type AnimationAlgorithm = (
  frame: number,
  config: AnimationConfig,
  target: AnimationTarget,
) => ColorGrid

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export interface AnimationConfig {
  /** Ordered array of hex color strings (the palette). */
  palette: string[]
  /** Speed multiplier (1.0 = normal). */
  speed: number
  /** Intensity 0.0-1.0 (controls density/brightness). */
  intensity: number
  /** Agent type for agent-specific animations. */
  agentType?: AgentType
}

// ---------------------------------------------------------------------------
// Render target
// ---------------------------------------------------------------------------

export interface LetterBoundary {
  /** Zero-based letter index within the word. */
  index: number
  /** First column (inclusive). */
  startCol: number
  /** Last column (inclusive). */
  endCol: number
  /** Human-readable label (e.g. "T", "E", "L"). */
  label: string
}

export interface AnimationTarget {
  /** Total pixel width. */
  width: number
  /** Total pixel height. */
  height: number
  /** All valid pixel coordinates as [x, y] tuples. */
  pixels: [number, number][]
  /** Letter boundaries for text-based targets. */
  letterBoundaries: LetterBoundary[]
  /** Get all pixels belonging to a specific letter. */
  getLetterPixels(letterIndex: number): [number, number][]
  /** Get all pixels in a specific row. */
  getRowPixels(row: number): [number, number][]
  /** Get all pixels in a specific column. */
  getColumnPixels(col: number): [number, number][]
}

// ---------------------------------------------------------------------------
// Priority system
// ---------------------------------------------------------------------------

export enum AnimationPriority {
  /** Lowest: ambient/idle animations. */
  PERIODIC = 0,
  /** Mid: triggered by agent events. */
  ACTIVITY = 1,
  /** Highest: user-triggered (party mode). */
  MANUAL = 2,
}

// ---------------------------------------------------------------------------
// Animation slot
// ---------------------------------------------------------------------------

export interface AnimationSlot {
  /** The pure algorithm that generates frames. */
  algorithm: AnimationAlgorithm
  /** Configuration (palette, speed, intensity). */
  config: AnimationConfig
  /** Priority level -- higher interrupts lower on the same target. */
  priority: AnimationPriority
  /** Frame counter value when this slot was started. */
  startFrame: number
  /** Total frames, or null for infinite (loop until replaced). */
  duration: number | null
  /** Identifier of the render target this slot animates. */
  targetId: string
}

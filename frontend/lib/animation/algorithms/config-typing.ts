/**
 * Typewriter effect across the target width.
 *
 * Each frame, a handful of random positions light up with random palette
 * colors, simulating flickering keystrokes. Randomness is seeded from the
 * frame number for deterministic output.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

/**
 * Simple deterministic PRNG (mulberry32).
 * Returns a function that yields values in [0, 1) on each call.
 */
function mulberry32(seed: number): () => number {
  let s = seed | 0
  return () => {
    s = (s + 0x6d2b79f5) | 0
    let t = Math.imul(s ^ (s >>> 15), 1 | s)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const NUM_FLICKERS = 5

export const configTyping: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const width = target.width
  if (width === 0) return grid

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const rng = mulberry32(frame * 2654435761)

  for (let i = 0; i < NUM_FLICKERS; i++) {
    const x = Math.floor(rng() * width)
    const colorIdx = Math.floor(rng() * paletteLen)
    grid.set(colorKey(x, 0), colorIdx)
  }
  return grid
}

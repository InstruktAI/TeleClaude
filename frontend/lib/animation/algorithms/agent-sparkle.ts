/**
 * Random pixels flash with random agent colors.
 *
 * Each frame, ~1/15th of all pixels are "sparked" with a random palette
 * color; the rest are cleared. Randomness is seeded from the frame number
 * for deterministic output.
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

export const agentSparkle: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const totalPixels = target.pixels.length
  if (totalPixels === 0) return grid

  const numSparkles = Math.max(1, Math.floor(totalPixels / 15))
  const rng = mulberry32(frame * 2654435761)

  // Clear all pixels first
  for (const [x, y] of target.pixels) {
    grid.set(colorKey(x, y), -1)
  }

  // Spark random pixels using Fisher-Yates partial shuffle
  const indices = Array.from({ length: totalPixels }, (_, i) => i)
  for (let i = 0; i < numSparkles; i++) {
    const j = i + Math.floor(rng() * (totalPixels - i))
    ;[indices[i], indices[j]] = [indices[j], indices[i]]
    const [x, y] = target.pixels[indices[i]]
    grid.set(colorKey(x, y), Math.floor(rng() * paletteLen))
  }

  return grid
}

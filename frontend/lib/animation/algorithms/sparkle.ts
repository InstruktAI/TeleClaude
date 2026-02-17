/**
 * Random pixels flash with palette colors.
 *
 * ~10% of pixels are lit each frame, with the rest cleared. Uses a
 * deterministic hash seeded from the frame number so the output is
 * pure (same frame always produces the same sparkle pattern).
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

/**
 * Simple deterministic hash for seeding sparkle positions.
 * Returns a value in [0, 1).
 */
function seededRandom(seed: number): number {
  // Based on a simple integer hash (xorshift-style).
  let s = (seed * 2654435761) >>> 0
  s = ((s ^ (s >>> 16)) * 2246822507) >>> 0
  s = ((s ^ (s >>> 13)) * 3266489909) >>> 0
  s = (s ^ (s >>> 16)) >>> 0
  return s / 4294967296
}

export const sparkle: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { pixels } = target

  const paletteLen = config.palette.length
  if (paletteLen === 0 || pixels.length === 0) return grid

  const density = Math.max(0.01, config.intensity * 0.2)

  // Clear all pixels first
  for (const [x, y] of pixels) {
    grid.set(colorKey(x, y), -1)
  }

  // Light up a fraction of pixels
  for (let i = 0; i < pixels.length; i++) {
    const r = seededRandom(frame * 100003 + i * 7919)
    if (r < density) {
      const [x, y] = pixels[i]
      const colorIdx = Math.floor(seededRandom(frame * 65537 + i * 6271) * paletteLen)
      grid.set(colorKey(x, y), colorIdx)
    }
  }

  return grid
}

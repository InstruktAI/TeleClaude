/**
 * Matrix-style falling columns of characters.
 *
 * Random columns activate and "rain" down at different speeds.
 * Head pixels use bright palette colors; tail pixels dim toward
 * the lowest palette index, creating a glowing-trail effect.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

function seededRandom(seed: number): () => number {
  let s = seed
  return () => {
    s = (s * 1664525 + 1013904223) & 0xffffffff
    return (s >>> 0) / 0xffffffff
  }
}

export const matrixRain: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { width, height } = target
  const paletteLen = config.palette.length
  if (paletteLen === 0 || width === 0 || height === 0) return grid

  const validPixels = new Set(target.pixels.map(([x, y]) => colorKey(x, y)))
  const tailLength = Math.max(3, height)
  const numDrops = Math.max(1, Math.ceil(width * config.intensity * 0.4))

  // Each column can host a raindrop. We simulate drop state per-column
  // deterministically by deriving column seeds from frame history.
  for (let d = 0; d < numDrops; d++) {
    // Stagger drop starts using a seed per drop slot
    const rng = seededRandom(d * 7919 + 31)
    const col = Math.floor(rng() * width)
    const speed = 1 + Math.floor(rng() * 2)
    const startFrame = Math.floor(rng() * (height + tailLength))

    // Position of the drop head at this frame
    const headRow = ((frame * speed + startFrame) % (height + tailLength)) - tailLength

    for (let t = 0; t < tailLength; t++) {
      const row = headRow - t
      if (row < 0 || row >= height) continue
      const key = colorKey(col, row)
      if (!validPixels.has(key)) continue

      // Head is brightest, tail fades
      const brightness = 1.0 - t / tailLength
      const colorIdx = Math.floor(brightness * (paletteLen - 1))
      // Only overwrite if brighter (head wins over tail of other drops)
      const existing = grid.get(key)
      if (existing === undefined || colorIdx > existing) {
        grid.set(key, colorIdx)
      }
    }
  }

  return grid
}

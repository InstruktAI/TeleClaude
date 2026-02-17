/**
 * Classic plasma effect using overlapping sine waves.
 *
 * Three sine functions with different frequencies and phase offsets
 * create an interference pattern. The combined value is mapped to
 * palette indices, producing a smoothly morphing, psychedelic wash.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const plasma: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { width, height } = target
  const paletteLen = config.palette.length
  if (paletteLen === 0 || width === 0 || height === 0) return grid

  const t = frame * config.speed * 0.05

  for (const [x, y] of target.pixels) {
    const nx = x / width
    const ny = y / height

    // Three overlapping sine waves with different spatial frequencies
    const v1 = Math.sin(nx * 6.0 + t)
    const v2 = Math.sin(ny * 8.0 + t * 1.3)
    const v3 = Math.sin((nx + ny) * 5.0 + t * 0.7)

    // Combine and normalize to [0, 1]
    const combined = (v1 + v2 + v3 + 3) / 6

    const colorIdx = Math.floor(combined * (paletteLen - 1))
    grid.set(colorKey(x, y), colorIdx)
  }

  return grid
}

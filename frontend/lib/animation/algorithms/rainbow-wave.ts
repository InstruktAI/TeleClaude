/**
 * Smooth rainbow sine wave across the target width.
 *
 * Each column gets a hue-shifted palette color determined by a sine
 * function. The wave scrolls horizontally over time, creating a
 * continuously flowing rainbow gradient.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const rainbowWave: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { width } = target
  const paletteLen = config.palette.length
  if (paletteLen === 0 || width === 0) return grid

  const speed = config.speed * 0.08
  const frequency = (2 * Math.PI) / width

  for (const [x, y] of target.pixels) {
    // Sine oscillation mapped to [0, 1]
    const wave = (Math.sin(x * frequency + frame * speed) + 1) / 2
    const colorIdx = Math.floor(wave * (paletteLen - 1))
    grid.set(colorKey(x, y), colorIdx)
  }

  return grid
}

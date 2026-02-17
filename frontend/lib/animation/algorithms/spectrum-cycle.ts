/**
 * All pixels synchronously cycle through the palette colors.
 *
 * Each frame advances the palette index by one, so the entire target
 * flashes uniformly through the full spectrum.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const spectrumCycle: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const colorIdx = frame % paletteLen

  for (const [x, y] of target.pixels) {
    grid.set(colorKey(x, y), colorIdx)
  }
  return grid
}

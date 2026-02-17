/**
 * All pixels pulse synchronously through agent palette colors.
 *
 * Each frame advances the palette index, so the entire target flashes
 * uniformly through the agent's color levels (subtle -> normal -> highlight).
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const agentPulse: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const colorIdx = frame % paletteLen

  for (const [x, y] of target.pixels) {
    grid.set(colorKey(x, y), colorIdx)
  }
  return grid
}

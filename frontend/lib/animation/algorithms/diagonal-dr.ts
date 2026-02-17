/**
 * Diagonal line sweeping down-right (top-left to bottom-right).
 *
 * Pixels where x + y equals the active diagonal value are lit; all
 * others are cleared. The diagonal value advances each frame across
 * width + height positions.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const diagonalDR: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { width, height } = target

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const maxVal = width + height
  if (maxVal === 0) return grid

  const active = frame % maxVal
  const colorIdx = Math.floor(frame / maxVal) % paletteLen

  for (const [x, y] of target.pixels) {
    if (x + y === active) {
      grid.set(colorKey(x, y), colorIdx)
    } else {
      grid.set(colorKey(x, y), -1)
    }
  }
  return grid
}

/**
 * Diagonal line sweeping down-left (top-right to bottom-left).
 *
 * Pixels where x - y equals the active diagonal value are lit; all
 * others are cleared. The diagonal value sweeps from -height to
 * width, advancing each frame.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const diagonalDL: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { width, height } = target

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const maxVal = width + height
  if (maxVal === 0) return grid

  const offset = height
  const active = (frame % maxVal) - offset
  const colorIdx = Math.floor(frame / maxVal) % paletteLen

  for (const [x, y] of target.pixels) {
    if (x - y === active) {
      grid.set(colorKey(x, y), colorIdx)
    } else {
      grid.set(colorKey(x, y), -1)
    }
  }
  return grid
}

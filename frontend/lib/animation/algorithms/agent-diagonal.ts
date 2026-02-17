/**
 * Diagonal wave using agent color sequence.
 *
 * A diagonal line (x + y = constant) sweeps across the target. Pixels
 * on the active diagonal get highlight, those within 3 cells get normal,
 * and the rest get subtle. Creates a rain-like diagonal wash effect.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const agentDiagonal: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const maxVal = target.width + target.height
  if (maxVal === 0) return grid

  const active = frame % maxVal

  const highlightIdx = Math.min(2, paletteLen - 1)
  const normalIdx = Math.min(1, paletteLen - 1)
  const subtleIdx = 0

  for (const [x, y] of target.pixels) {
    const dist = Math.abs((x + y) - active)
    let colorIdx: number
    if (dist === 0) {
      colorIdx = highlightIdx
    } else if (dist < 3) {
      colorIdx = normalIdx
    } else {
      colorIdx = subtleIdx
    }
    grid.set(colorKey(x, y), colorIdx)
  }
  return grid
}

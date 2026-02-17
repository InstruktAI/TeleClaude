/**
 * Vertical center expansion using agent colors.
 *
 * Rows expand outward from the vertical center of the target. Step 0
 * illuminates the center rows with highlight, step 1 one row further
 * with normal, step 2 the outermost reached rows with subtle. All
 * non-active rows are cleared.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const agentMiddleOut: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const height = target.height
  if (height < 2) return grid

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const midLow = Math.floor((height - 1) / 2)
  const midHigh = Math.ceil(height / 2)

  const maxSteps = Math.max(midLow + 1, height - midHigh)
  const step = frame % maxSteps

  // Center rows expand outward; palette index goes from highlight to subtle
  const activeRows = new Set<number>()
  const rowLow = midLow - step
  const rowHigh = midHigh + step
  if (rowLow >= 0) activeRows.add(rowLow)
  if (rowHigh < height) activeRows.add(rowHigh)

  // Step 0 (center) -> highlight (last palette idx), stepping out -> lower indices
  const paletteIdx = Math.max(0, paletteLen - 1 - step)
  const colorIdx = paletteIdx % paletteLen

  for (let r = 0; r < height; r++) {
    const rowPixels = target.getRowPixels(r)
    const value = activeRows.has(r) ? colorIdx : -1
    for (const [x, y] of rowPixels) {
      grid.set(colorKey(x, y), value)
    }
  }
  return grid
}

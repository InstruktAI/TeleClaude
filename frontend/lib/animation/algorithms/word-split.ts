/**
 * Alternating letters blink between two colors.
 *
 * Pixels are split into two groups based on their letter index (even
 * vs odd letters). On even frames the first group lights; on odd
 * frames the second group lights. The palette index advances every
 * two frames.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const wordSplit: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { letterBoundaries } = target

  const paletteLen = config.palette.length
  if (paletteLen === 0 || letterBoundaries.length === 0) return grid

  const parity = frame % 2
  const colorIdx = Math.floor(frame / 2) % paletteLen

  // Determine midpoint: first half vs second half of letters
  const midIdx = Math.floor(letterBoundaries.length / 2)
  const splitCol = midIdx > 0 ? letterBoundaries[midIdx].startCol : 0

  for (const [x, y] of target.pixels) {
    const isFirstHalf = x < splitCol
    if ((isFirstHalf && parity === 0) || (!isFirstHalf && parity === 1)) {
      grid.set(colorKey(x, y), colorIdx)
    } else {
      grid.set(colorKey(x, y), -1)
    }
  }
  return grid
}

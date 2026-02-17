/**
 * Alternating words in agent colors.
 *
 * Splits the target into two halves (e.g. "TELE" and "CLAUDE") at roughly
 * 40% of the width. On even frames the left half gets the highlight color
 * and the right half gets subtle; on odd frames they swap.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const agentWordSplit: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  // Split at ~40% of width (matches Python: 33/82 for big, 15/39 for small)
  const splitX = Math.round(target.width * 0.4)
  const highlightIdx = Math.min(2, paletteLen - 1)
  const subtleIdx = 0
  const parity = frame % 2

  for (const [x, y] of target.pixels) {
    const isLeft = x < splitX
    const isHighlighted = (isLeft && parity === 0) || (!isLeft && parity === 1)
    grid.set(colorKey(x, y), isHighlighted ? highlightIdx : subtleIdx)
  }
  return grid
}

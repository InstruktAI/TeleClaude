/**
 * Color sweeps within each letter, right to left.
 *
 * Identical to within-letter-lr but the active column counts from the
 * right edge of each letter toward the left.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const withinLetterRL: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { letterBoundaries } = target
  if (letterBoundaries.length === 0) return grid

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  for (const boundary of letterBoundaries) {
    const letterWidth = boundary.endCol - boundary.startCol + 1
    if (letterWidth <= 0) continue

    const activeColOffset = (letterWidth - 1) - (frame % letterWidth)
    const activeCol = boundary.startCol + activeColOffset
    const colorIdx = Math.floor(frame / letterWidth) % paletteLen

    for (let x = boundary.startCol; x <= boundary.endCol; x++) {
      const colPixels = target.getColumnPixels(x)
      const value = x === activeCol ? colorIdx : -1
      for (const [px, py] of colPixels) {
        grid.set(colorKey(px, py), value)
      }
    }
  }
  return grid
}

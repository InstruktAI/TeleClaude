/**
 * Color sweeps within each letter, left to right.
 *
 * For each letter, only one column at a time is active. The sweep
 * position is based on the letter's own width and boundaries. All
 * letters sweep in parallel.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const withinLetterLR: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { letterBoundaries } = target
  if (letterBoundaries.length === 0) return grid

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  for (const boundary of letterBoundaries) {
    const letterWidth = boundary.endCol - boundary.startCol + 1
    if (letterWidth <= 0) continue

    const activeColOffset = frame % letterWidth
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

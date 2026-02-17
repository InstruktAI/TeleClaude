/**
 * Within each letter, a single column sweeps left-to-right using agent colors.
 *
 * All letters sweep in parallel. The active column advances each frame
 * relative to each letter's own start position. The palette color cycles
 * on each full pass through the widest letter.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const agentWithinLetter: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const numLetters = target.letterBoundaries.length
  if (numLetters === 0) return grid

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  for (let i = 0; i < numLetters; i++) {
    const boundary = target.letterBoundaries[i]
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

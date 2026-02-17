/**
 * Letters light up one by one in a cascade.
 *
 * Each frame illuminates one letter while clearing the rest. Each letter
 * is assigned a fixed palette color based on its index (cycling through
 * the palette length). The active letter advances sequentially.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const agentLetterCascade: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const numLetters = target.letterBoundaries.length
  if (numLetters === 0) return grid

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const activeLetter = frame % numLetters

  for (let i = 0; i < numLetters; i++) {
    const colorIdx = i % paletteLen
    const pixels = target.getLetterPixels(i)
    const value = i === activeLetter ? colorIdx : -1
    for (const [x, y] of pixels) {
      grid.set(colorKey(x, y), value)
    }
  }
  return grid
}

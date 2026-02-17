/**
 * Wave of color sweeping left-to-right, letter by letter.
 *
 * One letter is active at a time; all others are cleared. The active
 * letter index advances each frame, cycling through the palette on
 * each full pass.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const letterWaveLR: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const numLetters = target.letterBoundaries.length
  if (numLetters === 0) return grid

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const activeLetterIdx = frame % numLetters
  const colorIdx = Math.floor(frame / numLetters) % paletteLen

  for (let i = 0; i < numLetters; i++) {
    const pixels = target.getLetterPixels(i)
    const value = i === activeLetterIdx ? colorIdx : -1
    for (const [x, y] of pixels) {
      grid.set(colorKey(x, y), value)
    }
  }
  return grid
}

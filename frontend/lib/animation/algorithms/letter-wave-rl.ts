/**
 * Wave of color sweeping right-to-left, letter by letter.
 *
 * Identical to letter-wave-lr but the active letter index counts
 * down from the last letter to the first.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const letterWaveRL: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const numLetters = target.letterBoundaries.length
  if (numLetters === 0) return grid

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const activeLetterIdx = (numLetters - 1) - (frame % numLetters)
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

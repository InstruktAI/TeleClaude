/**
 * Color wave sweeping right-to-left, letter by letter, using agent colors.
 *
 * Mirror of agentWaveLR: the active letter starts at the rightmost letter
 * and moves leftward. All inactive letters are cleared (-1).
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const agentWaveRL: AnimationAlgorithm = (frame, config, target) => {
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

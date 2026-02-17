/**
 * Alternating checkerboard pattern of palette colors.
 *
 * Pixels where (x + y) % 2 matches the frame parity are lit; the
 * rest are cleared. The palette index advances every two frames.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const checkerboard: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const parity = frame % 2
  const colorIdx = Math.floor(frame / 2) % paletteLen

  for (const [x, y] of target.pixels) {
    if ((x + y) % 2 === parity) {
      grid.set(colorKey(x, y), colorIdx)
    } else {
      grid.set(colorKey(x, y), -1)
    }
  }
  return grid
}

/**
 * Section label pulses with a moving gradient wave.
 *
 * A color gradient scrolls horizontally across the center 80% of the
 * target width. The offset advances each frame based on progress through
 * the animation duration. Works with variable-width config-section targets.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const configPulse: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const width = target.width
  if (width === 0) return grid

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const barWidth = Math.max(1, Math.floor(width * 0.8))
  const startX = Math.floor((width - barWidth) / 2)
  const offset = frame % width

  for (let x = 0; x < width; x++) {
    if (x >= startX && x < startX + barWidth) {
      const val = (x + offset) % width
      const colorIdx = Math.floor((val / width) * paletteLen) % paletteLen
      grid.set(colorKey(x, 0), colorIdx)
    }
  }
  return grid
}
